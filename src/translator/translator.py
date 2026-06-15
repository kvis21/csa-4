# translator/translator.py
"""
Транслятор Forth-подобного языка в машинный код Harvard RISC-процессора.

Архитектура:
  - Pass 1: рекурсивный спуск по токенам, генерация инструкций с заглушками-метками
  - Pass 2: линковка — разрешение всех LABEL-аргументов в числовые адреса IMEM/DMEM

Соглашения о регистрах (только внутри вспомогательных инструкций транслятора):
  R1 — временный регистр (scratch / TOS при переносе)
  R2 — временный регистр (second при бинарных операциях)
  R3 — временный регистр (third, ROT и т.п.)
  R4 — используется для EXECUTE (indirect call)
  R0 — всегда 0 (hardwired zero, не трогаем)

Стек данных реализован аппаратным SP (PUSH/POP).
Стек возвратов — аппаратный RP (CALL/RET/IRET).
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional
import itertools

from isa import Opcode, Instruction, Arg, ArgType, Register
from translator.tokenizer import Token, TokenType

_label_counter = itertools.count()

def _uid() -> str:
    return str(next(_label_counter))

@dataclass
class Program:
    """Представление скомпилированной программы."""
    instructions: List[Instruction] = field(default_factory=list)
    data_memory:  List[int]         = field(default_factory=list)

    labels:    Dict[str, int] = field(default_factory=dict)   # имя -> адрес IMEM
    variables: Dict[str, int] = field(default_factory=dict)   # имя -> адрес DMEM

    # Таблица векторов прерываний: номер вектора -> адрес IMEM
    isr_table: Dict[int, int] = field(default_factory=dict)

    def allocate_string(self, text: str) -> int:
        """Pascal-string: [len, ch0, ch1, ...] в DMEM. Возвращает адрес."""
        addr = len(self.data_memory)
        self.data_memory.append(len(text))
        for ch in text:
            self.data_memory.append(ord(ch))
        return addr

    def allocate_variable(self, initial: int = 0) -> int:
        addr = len(self.data_memory)
        self.data_memory.append(initial)
        return addr

    # -----------------------------------------------------------------------
    # Кодогенерация (Pass 2 уже разрешил все LABEL -> ADDR)
    # -----------------------------------------------------------------------
    def to_machine_code(self) -> List[str]:
        result = []
        for instr in self.instructions:
            result.append(self._encode(instr))
        return result

    def _encode(self, instr: Instruction) -> str:
        opc = int(instr.opcode.value) & 0x7F

        def val(arg: Arg) -> int:
            if arg.arg_type == ArgType.REG:
                return int(arg.value) & 0x7
            return int(arg.value)

        word = 0

        if instr.opcode in (Opcode.LD, Opcode.ST):
            rd = val(instr.args[0])
            am = 1 if instr.am == 1 else 0
            if am == 0:
                addr = val(instr.args[1]) & 0x1FFFFF
                word = (opc << 25) | (rd << 22) | (am << 21) | addr
            else:
                rs = val(instr.args[1])
                word = (opc << 25) | (rd << 22) | (am << 21) | (rs << 18)

        elif instr.opcode == Opcode.LUI:
            rd   = val(instr.args[0])
            imm  = val(instr.args[1]) & 0x3FFFFF
            word = (opc << 25) | (rd << 22) | imm

        elif instr.opcode in (Opcode.ADD, Opcode.SUB, Opcode.MUL,
                               Opcode.DIV, Opcode.MOD, Opcode.CMP):
            if instr.opcode == Opcode.CMP:
                rd, rs1, sec = 0, val(instr.args[0]), instr.args[1]
            else:
                rd, rs1, sec = val(instr.args[0]), val(instr.args[1]), instr.args[2]
            am = 1 if instr.am == 1 else 0
            if am == 1:
                imm = val(sec) & 0x3FFFF
                word = (opc << 25) | (rd << 22) | (rs1 << 19) | (am << 18) | imm
            else:
                rs2 = val(sec)
                word = (opc << 25) | (rd << 22) | (rs1 << 19) | (am << 18) | (rs2 << 15)

        elif instr.opcode in (Opcode.JMP, Opcode.BEQ, Opcode.BNE,
                               Opcode.BGT, Opcode.BLT, Opcode.CALL):
            addr = val(instr.args[0]) & 0x1FFFFFF
            word = (opc << 25) | addr

        elif instr.opcode in (Opcode.IN, Opcode.OUT):
            reg  = val(instr.args[0])
            port = val(instr.args[1]) & 0x3FFFFF
            word = (opc << 25) | (reg << 22) | port

        elif instr.opcode in (Opcode.PUSH, Opcode.POP):
            reg  = val(instr.args[0])
            word = (opc << 25) | (reg << 22)

        elif instr.opcode in (Opcode.RET, Opcode.EI, Opcode.DI, Opcode.IRET, Opcode.HLT):
            word = opc << 25

        return f"{word:032b}"
# ---------------------------------------------------------------------------
# Вспомогательные эмиттеры инструкций
# ---------------------------------------------------------------------------

R0 = Register.R0
R1 = Register.R1
R2 = Register.R2
R3 = Register.R3
R4 = Register.R4

def _reg(r: Register) -> Arg:
    return Arg(r, ArgType.REG)

def _imm(v: int) -> Arg:
    return Arg(v, ArgType.IMM)

def _addr(v: int) -> Arg:
    return Arg(v, ArgType.ADDR)

def _lbl(name: str) -> Arg:
    return Arg(name, ArgType.LABEL)

def emit(p: Program, instr: Instruction) -> int:
    """Добавить инструкцию, вернуть её адрес."""
    addr = len(p.instructions)
    p.instructions.append(instr)
    return addr

def _push_const(p: Program, val: int, comment: str = "") -> None:
    """Загрузить 32-битную константу в R1 и положить на стек."""
    upper = (val >> 10) & 0x3FFFFF
    lower = val & 0x3FF
    emit(p, Instruction(Opcode.LUI, [_reg(R1), _imm(upper)],
                        comment=comment or f"LUI #{upper} (const {val})"))
    emit(p, Instruction(Opcode.ADD, [_reg(R1), _reg(R1), _imm(lower)],
                        am=1, comment=f"ADD #{lower} (const {val})"))
    emit(p, Instruction(Opcode.PUSH, [_reg(R1)], comment=f"PUSH {val}"))

def _push_label(p: Program, lbl: str, comment: str = "") -> None:
    """Положить на стек адрес метки (разрешается при линковке через R1)."""
    emit(p, Instruction(Opcode.LUI,  [_reg(R1), _lbl(f"__lui__{lbl}")],
                        comment=comment or f"LUI addr({lbl})"))
    emit(p, Instruction(Opcode.ADD,  [_reg(R1), _reg(R1), _lbl(f"__low__{lbl}")],
                        am=1, comment=f"ADD low addr({lbl})"))
    emit(p, Instruction(Opcode.PUSH, [_reg(R1)], comment=f"PUSH xt({lbl})"))

def _push_true(p: Program) -> None:
    """Положить 1 (True) на стек."""
    _push_const(p, 1, "push TRUE(1)")

def _push_false(p: Program) -> None:
    """Положить 0 (False) на стек."""
    emit(p, Instruction(Opcode.LUI, [_reg(R1), _imm(0)], comment="LUI 0 (FALSE)"))
    emit(p, Instruction(Opcode.ADD, [_reg(R1), _reg(R1), _imm(0)], am=1, comment="ADD 0"))
    emit(p, Instruction(Opcode.PUSH, [_reg(R1)], comment="PUSH FALSE(0)"))
# ---------------------------------------------------------------------------
# Трансляция: рекурсивный спуск по токенам
# ---------------------------------------------------------------------------

class Translator:
    def __init__(self, tokens: List[Token], program: Program):
        self.tokens  = tokens
        self.pos     = 0
        self.program = program

    # ------------------------------------------------------------------
    def peek(self) -> Optional[Token]:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def consume(self) -> Token:
        t = self.tokens[self.pos]
        self.pos += 1
        return t

    def expect(self, value: str) -> Token:
        t = self.consume()
        if t.value.upper() != value.upper():
            raise SyntaxError(
                f"Строка {t.line}: ожидалось '{value}', получено '{t.value}'"
            )
        return t

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    def translate(self) -> None:
        p = self.program
        emit(p, Instruction(Opcode.CALL, [_lbl("MAIN")], comment="Call entry point"))
        emit(p, Instruction(Opcode.HLT, [], comment="Stop execution"))

        main_addr = None

        while self.pos < len(self.tokens):
            t = self.peek()
            if t is None:
                break
            
            w = t.value.upper()
            if w not in ("VARIABLE", ":", "MAIN") and main_addr is None:
                main_addr = len(p.instructions)

            self._translate_word()

        if main_addr is not None:
            emit(p, Instruction(Opcode.RET, [], comment="RET from MAIN"))

        if "MAIN" not in p.labels:
            p.labels["MAIN"] = main_addr if main_addr is not None else len(p.instructions)

        self._link()
    # ------------------------------------------------------------------
    def _translate_word(self) -> None:
        t = self.peek()
        if t is None:
            return
        w = t.value
        wu = w.upper()

        # ИГНОРИРУЕМ "MAIN", если он встретился как отдельное слово в коде
        # (потому что мы уже сгенерировали JMP на него в начале)
        if wu == "MAIN" and self.pos == self.pos:
             self.consume()
             return

        # ------ Переменные ------
        if wu == "VARIABLE":
            self.consume()
            name_tok = self.consume()
            addr = self.program.allocate_variable(0)
            self.program.variables[name_tok.value] = addr
            return

        # ------ Определение процедуры : NAME ... ; ------
        if w == ":":
            self.consume()
            name_tok = self.consume()
            name = name_tok.value
            self.program.labels[name] = len(self.program.instructions)
            # Тело до ;
            while self.pos < len(self.tokens) and self.peek().value != ";":
                self._translate_word()
            self.expect(";")
            emit(self.program, Instruction(Opcode.RET, [], comment=f"RET from {name}"))
            return

        # ------ Строковые литералы ------
        if t.type == TokenType.STRING:
            self.consume()
            text = w[2:-1]  # P"text" -> text
            addr = self.program.allocate_string(text)
            _push_const(self.program, addr, f"PUSH addr of pstr \"{text}\"")
            return

        # ------ Числа ------
        if t.type == TokenType.NUMBER:
            self.consume()
            _push_const(self.program, int(w), f"PUSH {w}")
            return

        # ------ Управляющие конструкции ------
        if wu == "IF":
            self.consume()
            self._translate_if()
            return

        if wu == "BEGIN":
            self.consume()
            self._translate_begin()
            return

        if wu == "DO":
            self.consume()
            self._translate_do()
            return

        # ------ Прерывания ------
        if wu == "EI":
            self.consume()
            emit(self.program, Instruction(Opcode.EI, [], comment="EI"))
            return

        if wu == "DI":
            self.consume()
            emit(self.program, Instruction(Opcode.DI, [], comment="DI"))
            return

        if wu == "IRET":
            self.consume()
            emit(self.program, Instruction(Opcode.IRET, [], comment="IRET"))
            return

        if wu == "SET-ISR":
            self.consume()
            self._emit_set_isr()
            return

        # ------ ' (tick) — execution token ------
        if w == "'":
            self.consume()
            name_tok = self.consume()
            _push_label(self.program, name_tok.value,
                        comment=f"tick: push xt of {name_tok.value}")
            return

        # ------ EXECUTE ------
        if wu == "EXECUTE":
            self.consume()
            self._emit_execute()
            return

        # ------ Встроенные Forth-слова ------
        if wu in _BUILTINS:
            self.consume()
            _BUILTINS[wu](self.program)
            return

        # ------ Имя переменной ------
        if w in self.program.variables:
            self.consume()
            addr = self.program.variables[w]
            _push_const(self.program, addr, f"PUSH addr({w})")
            return

        # ------ Имя процедуры (уже известной или forward-ref) ------
        # Также обработка "MAIN" как метки точки входа
        if wu == "MAIN" and w == "MAIN":
            self.consume()
            self.program.labels["MAIN"] = len(self.program.instructions)
            return

        self.consume()
        emit(self.program,
             Instruction(Opcode.CALL, [_lbl(w)], comment=f"CALL {w}"))

    # ------------------------------------------------------------------
    # IF ... [ELSE ...] THEN
    # ------------------------------------------------------------------
    def _translate_if(self) -> None:
        p = self.program
        uid = _uid()

        emit(p, Instruction(Opcode.POP, [_reg(R1)], comment="IF: pop condition"))
        emit(p, Instruction(Opcode.CMP, [_reg(R1), _reg(R0)], am=0,
                            comment="IF: CMP with 0"))
        lbl_else = f"__else_{uid}"
        emit(p, Instruction(Opcode.BEQ, [_lbl(lbl_else)],
                            comment="IF: BEQ to else/then"))

        # Тело IF
        while self.pos < len(self.tokens):
            nw = self.peek().value.upper()
            if nw in ("ELSE", "THEN"):
                break
            self._translate_word()

        lbl_end = f"__then_{uid}"

        if self.peek() and self.peek().value.upper() == "ELSE":
            self.consume()
            # Прыжок через ELSE-ветку
            emit(p, Instruction(Opcode.JMP, [_lbl(lbl_end)],
                                comment="IF: JMP over ELSE"))
            p.labels[lbl_else] = len(p.instructions)
            while self.pos < len(self.tokens):
                nw = self.peek().value.upper()
                if nw == "THEN":
                    break
                self._translate_word()
        else:
            p.labels[lbl_else] = len(p.instructions)

        self.expect("THEN")
        p.labels[lbl_end] = len(p.instructions)

    # ------------------------------------------------------------------
    # BEGIN ... UNTIL         (постусловие: выход если TOS != 0)
    # BEGIN ... WHILE ... REPEAT  (предусловие)
    # ------------------------------------------------------------------
    def _translate_begin(self) -> None:
        p = self.program
        uid = _uid()
        lbl_begin = f"__begin_{uid}"
        p.labels[lbl_begin] = len(p.instructions)

        while self.pos < len(self.tokens):
            nw = self.peek().value.upper()
            if nw in ("UNTIL", "WHILE"):
                break
            self._translate_word()

        nw = self.peek().value.upper() if self.peek() else ""

        if nw == "UNTIL":
            self.consume()
            emit(p, Instruction(Opcode.POP, [_reg(R1)],
                                comment="UNTIL: pop condition"))
            emit(p, Instruction(Opcode.CMP, [_reg(R1), _reg(R0)], am=0,
                                comment="UNTIL: CMP with 0"))
            emit(p, Instruction(Opcode.BEQ, [_lbl(lbl_begin)],
                                comment="UNTIL: BEQ back if false"))

        elif nw == "WHILE":
            self.consume()
            emit(p, Instruction(Opcode.POP, [_reg(R1)],
                                comment="WHILE: pop condition"))
            emit(p, Instruction(Opcode.CMP, [_reg(R1), _reg(R0)], am=0,
                                comment="WHILE: CMP with 0"))
            lbl_repeat_end = f"__repeat_{uid}"
            emit(p, Instruction(Opcode.BEQ, [_lbl(lbl_repeat_end)],
                                comment="WHILE: BEQ exit loop if false"))

            while self.pos < len(self.tokens):
                nw2 = self.peek().value.upper()
                if nw2 == "REPEAT":
                    break
                self._translate_word()

            self.expect("REPEAT")
            emit(p, Instruction(Opcode.JMP, [_lbl(lbl_begin)],
                                comment="REPEAT: JMP back to BEGIN"))
            p.labels[lbl_repeat_end] = len(p.instructions)

    # ------------------------------------------------------------------
    # DO ... LOOP  ( limit start -- )
    # ------------------------------------------------------------------
    def _translate_do(self) -> None:
        p = self.program
        uid = _uid()

        lbl_i     = f"__do_i_{uid}"
        lbl_limit = f"__do_limit_{uid}"
        addr_i     = p.allocate_variable(0)
        addr_limit = p.allocate_variable(0)
        p.variables[lbl_i]     = addr_i
        p.variables[lbl_limit] = addr_limit

        emit(p, Instruction(Opcode.POP, [_reg(R1)], comment="DO: pop start -> R1"))
        emit(p, Instruction(Opcode.ST,  [_reg(R1), _addr(addr_i)], am=0,
                            comment="DO: store start -> I"))
        emit(p, Instruction(Opcode.POP, [_reg(R1)], comment="DO: pop limit -> R1"))
        emit(p, Instruction(Opcode.ST,  [_reg(R1), _addr(addr_limit)], am=0,
                            comment="DO: store limit -> LIMIT"))

        lbl_do_top = f"__do_top_{uid}"
        lbl_do_end = f"__do_end_{uid}"
        p.labels[lbl_do_top] = len(p.instructions)

        emit(p, Instruction(Opcode.LD, [_reg(R1), _addr(addr_i)], am=0,
                            comment="DO: load I"))
        emit(p, Instruction(Opcode.LD, [_reg(R2), _addr(addr_limit)], am=0,
                            comment="DO: load LIMIT"))
        emit(p, Instruction(Opcode.CMP, [_reg(R1), _reg(R2)], am=0,
                            comment="DO: CMP I, LIMIT"))
        emit(p, Instruction(Opcode.BEQ, [_lbl(lbl_do_end)],
                            comment="DO: exit if I == LIMIT"))
        emit(p, Instruction(Opcode.BGT, [_lbl(lbl_do_end)],
                            comment="DO: exit if I > LIMIT"))

        while self.pos < len(self.tokens):
            nw = self.peek().value.upper()
            if nw == "LOOP":
                break
            if nw == "I" and self.peek().value == "I":
                self.consume()
                emit(p, Instruction(Opcode.LD, [_reg(R1), _addr(addr_i)], am=0,
                                    comment="I: load loop counter"))
                emit(p, Instruction(Opcode.PUSH, [_reg(R1)], comment="I: push"))
                continue
            self._translate_word()
        self.expect("LOOP")

        emit(p, Instruction(Opcode.LD,  [_reg(R1), _addr(addr_i)], am=0,
                            comment="LOOP: load I"))
        emit(p, Instruction(Opcode.ADD, [_reg(R1), _reg(R1), _imm(1)], am=1,
                            comment="LOOP: I++"))
        emit(p, Instruction(Opcode.ST,  [_reg(R1), _addr(addr_i)], am=0,
                            comment="LOOP: store I"))
        emit(p, Instruction(Opcode.JMP, [_lbl(lbl_do_top)],
                            comment="LOOP: JMP back"))
        p.labels[lbl_do_end] = len(p.instructions)

    def _emit_set_isr(self) -> None:
        p = self.program
        if "__isr_table__" not in p.variables:
            base = len(p.data_memory)
            for _ in range(8):
                p.data_memory.append(0)
            p.variables["__isr_table__"] = base
        base = p.variables["__isr_table__"]
        
        emit(p, Instruction(Opcode.POP, [_reg(R2)], comment="SET-ISR: pop vector_num -> R2"))
        emit(p, Instruction(Opcode.POP, [_reg(R1)], comment="SET-ISR: pop xt -> R1"))
        emit(p, Instruction(Opcode.ADD, [_reg(R3), _reg(R2), _imm(base)], am=1,
                            comment="SET-ISR: R3 = base + vector"))
        emit(p, Instruction(Opcode.ST,  [_reg(R1), _reg(R3)], am=1,
                            comment="SET-ISR: mem[R3] = xt"))

    def _emit_execute(self) -> None:
        p = self.program
        if "__execute_trampoline__" not in p.labels:
            pass
        
        emit(p, Instruction(Opcode.POP, [_reg(R4)], comment="EXECUTE: pop xt -> R4"))

        if "__exec_cell__" not in p.variables:
            p.variables["__exec_cell__"] = p.allocate_variable(0)

        cell = p.variables["__exec_cell__"]
        emit(p, Instruction(Opcode.ST, [_reg(R4), _addr(cell)], am=0,
                            comment="EXECUTE: store xt"))
        emit(p, Instruction(Opcode.CALL, [_lbl("__execute_dispatch__")],
                            comment="EXECUTE: call dispatch"))

    # ------------------------------------------------------------------
    # Pass 2: линковка
    # ------------------------------------------------------------------
    def _link(self) -> None:
        p = self.program
        
        if "__exec_cell__" in p.variables:
            self._generate_execute_dispatch()

        for instr in p.instructions:
            for arg in instr.args:
                if arg.arg_type == ArgType.LABEL:
                    name = arg.value
                    if name.startswith("__lui__"):
                        proc = name[len("__lui__"):]
                        real_addr = p.labels.get(proc, p.variables.get(proc, 0))
                        arg.arg_type = ArgType.IMM
                        arg.value = (real_addr >> 10) & 0x3FFFFF
                    elif name.startswith("__low__"):
                        proc = name[len("__low__"):]
                        real_addr = p.labels.get(proc, p.variables.get(proc, 0))
                        arg.arg_type = ArgType.IMM
                        arg.value = real_addr & 0x3FF

        for instr in p.instructions:
            for arg in instr.args:
                if arg.arg_type == ArgType.LABEL:
                    name = arg.value
                    if name in p.variables:
                        arg.arg_type = ArgType.ADDR
                        arg.value = p.variables[name]
                    elif name in p.labels:
                        arg.arg_type = ArgType.ADDR
                        arg.value = p.labels[name]
                    else:
                        raise Exception(f"Линковщик: неразрешённая метка '{name}'")

    def _generate_execute_dispatch(self) -> None:
        """Генерирует диспетчер для EXECUTE."""
        p = self.program
        if "__execute_dispatch__" in p.labels:
            return

        cell = p.variables["__exec_cell__"]
        p.labels["__execute_dispatch__"] = len(p.instructions)

        emit(p, Instruction(Opcode.LD, [_reg(R4), _addr(cell)], am=0,
                            comment="EXEC_DISP: load xt"))

        lbl_disp_end = "__exec_disp_end__"

        for proc_name, proc_addr in list(p.labels.items()):
            if proc_name.startswith("__"):
                continue              
            uid = _uid()
            lbl_no_match = f"__exec_no_{uid}"
            upper = (proc_addr >> 10) & 0x3FFFFF
            lower = proc_addr & 0x3FF
            emit(p, Instruction(Opcode.LUI, [_reg(R3), _imm(upper)],
                                comment=f"DISP: load addr of {proc_name} upper"))
            emit(p, Instruction(Opcode.ADD, [_reg(R3), _reg(R3), _imm(lower)],
                                am=1, comment=f"DISP: load addr of {proc_name} lower"))
            emit(p, Instruction(Opcode.CMP, [_reg(R4), _reg(R3)], am=0,
                                comment=f"DISP: CMP xt == {proc_name}?"))
            emit(p, Instruction(Opcode.BNE, [_lbl(lbl_no_match)],
                                comment=f"DISP: BNE skip {proc_name}"))
            emit(p, Instruction(Opcode.CALL, [_addr(proc_addr)],
                                comment=f"DISP: CALL {proc_name}"))
            emit(p, Instruction(Opcode.RET, [], comment="DISP: RET after dispatch"))
            p.labels[lbl_no_match] = len(p.instructions)

            emit(p, Instruction(Opcode.RET, [], comment="EXEC_DISP: no match, RET"))
        p.labels[lbl_disp_end] = len(p.instructions)

def _bi_dup(p: Program):
    emit(p, Instruction(Opcode.POP,  [_reg(R1)], comment="DUP: pop TOS"))
    emit(p, Instruction(Opcode.PUSH, [_reg(R1)], comment="DUP: push copy 1"))
    emit(p, Instruction(Opcode.PUSH, [_reg(R1)], comment="DUP: push copy 2"))

def _bi_drop(p: Program):
    emit(p, Instruction(Opcode.POP, [_reg(R1)], comment="DROP"))

def _bi_swap(p: Program):
    emit(p, Instruction(Opcode.POP,  [_reg(R1)], comment="SWAP: pop TOS"))
    emit(p, Instruction(Opcode.POP,  [_reg(R2)], comment="SWAP: pop 2nd"))
    emit(p, Instruction(Opcode.PUSH, [_reg(R1)], comment="SWAP: push old TOS"))
    emit(p, Instruction(Opcode.PUSH, [_reg(R2)], comment="SWAP: push old 2nd"))

def _bi_over(p: Program):
    emit(p, Instruction(Opcode.POP,  [_reg(R1)], comment="OVER: pop TOS"))
    emit(p, Instruction(Opcode.POP,  [_reg(R2)], comment="OVER: pop 2nd"))
    emit(p, Instruction(Opcode.PUSH, [_reg(R2)], comment="OVER: push 2nd"))
    emit(p, Instruction(Opcode.PUSH, [_reg(R1)], comment="OVER: push TOS"))
    emit(p, Instruction(Opcode.PUSH, [_reg(R2)], comment="OVER: push copy of 2nd"))

def _bi_rot(p: Program):
    emit(p, Instruction(Opcode.POP,  [_reg(R1)], comment="ROT: pop TOS"))
    emit(p, Instruction(Opcode.POP,  [_reg(R2)], comment="ROT: pop 2nd"))
    emit(p, Instruction(Opcode.POP,  [_reg(R3)], comment="ROT: pop 3rd"))
    emit(p, Instruction(Opcode.PUSH, [_reg(R2)], comment="ROT: push 2nd"))
    emit(p, Instruction(Opcode.PUSH, [_reg(R1)], comment="ROT: push TOS"))
    emit(p, Instruction(Opcode.PUSH, [_reg(R3)], comment="ROT: push 3rd on top"))

def _bi_nrot(p: Program):
    # -ROT ( a b c -- c a b )
    emit(p, Instruction(Opcode.POP,  [_reg(R1)], comment="-ROT: pop TOS(c)"))
    emit(p, Instruction(Opcode.POP,  [_reg(R2)], comment="-ROT: pop 2nd(b)"))
    emit(p, Instruction(Opcode.POP,  [_reg(R3)], comment="-ROT: pop 3rd(a)"))
    emit(p, Instruction(Opcode.PUSH, [_reg(R1)], comment="-ROT: push c"))
    emit(p, Instruction(Opcode.PUSH, [_reg(R3)], comment="-ROT: push a"))
    emit(p, Instruction(Opcode.PUSH, [_reg(R2)], comment="-ROT: push b"))

def _bi_tuck(p: Program):
    # TUCK ( a b -- b a b )
    emit(p, Instruction(Opcode.POP,  [_reg(R1)], comment="TUCK: pop TOS(b)"))
    emit(p, Instruction(Opcode.POP,  [_reg(R2)], comment="TUCK: pop 2nd(a)"))
    emit(p, Instruction(Opcode.PUSH, [_reg(R1)], comment="TUCK: push b"))
    emit(p, Instruction(Opcode.PUSH, [_reg(R2)], comment="TUCK: push a"))
    emit(p, Instruction(Opcode.PUSH, [_reg(R1)], comment="TUCK: push b again"))

def _bi_add(p: Program):
    emit(p, Instruction(Opcode.POP,  [_reg(R2)], comment="+ pop TOS"))
    emit(p, Instruction(Opcode.POP,  [_reg(R1)], comment="+ pop 2nd"))
    emit(p, Instruction(Opcode.ADD,  [_reg(R1), _reg(R1), _reg(R2)], am=0, comment="+ ADD"))
    emit(p, Instruction(Opcode.PUSH, [_reg(R1)], comment="+ push result"))

def _bi_sub(p: Program):
    emit(p, Instruction(Opcode.POP,  [_reg(R2)], comment="- pop TOS"))
    emit(p, Instruction(Opcode.POP,  [_reg(R1)], comment="- pop 2nd"))
    emit(p, Instruction(Opcode.SUB,  [_reg(R1), _reg(R1), _reg(R2)], am=0, comment="- SUB"))
    emit(p, Instruction(Opcode.PUSH, [_reg(R1)], comment="- push result"))

def _bi_mul(p: Program):
    emit(p, Instruction(Opcode.POP,  [_reg(R2)], comment="* pop TOS"))
    emit(p, Instruction(Opcode.POP,  [_reg(R1)], comment="* pop 2nd"))
    emit(p, Instruction(Opcode.MUL,  [_reg(R1), _reg(R1), _reg(R2)], am=0, comment="* MUL"))
    emit(p, Instruction(Opcode.PUSH, [_reg(R1)], comment="* push result"))

def _bi_div(p: Program):
    emit(p, Instruction(Opcode.POP,  [_reg(R2)], comment="/ pop TOS"))
    emit(p, Instruction(Opcode.POP,  [_reg(R1)], comment="/ pop 2nd"))
    emit(p, Instruction(Opcode.DIV,  [_reg(R1), _reg(R1), _reg(R2)], am=0, comment="/ DIV"))
    emit(p, Instruction(Opcode.PUSH, [_reg(R1)], comment="/ push result"))

def _bi_mod(p: Program):
    emit(p, Instruction(Opcode.POP,  [_reg(R2)], comment="MOD pop TOS"))
    emit(p, Instruction(Opcode.POP,  [_reg(R1)], comment="MOD pop 2nd"))
    emit(p, Instruction(Opcode.MOD,  [_reg(R1), _reg(R1), _reg(R2)], am=0, comment="MOD"))
    emit(p, Instruction(Opcode.PUSH, [_reg(R1)], comment="MOD push result"))

def _bi_cmp_op(opcode_branch: Opcode, name: str):
    """Фабрика: ( a b -- 1/0 ) через CMP + ветвление."""
    def _impl(p: Program):
        uid = _uid()
        lbl_true = f"__{name}_t_{uid}"
        lbl_end  = f"__{name}_e_{uid}"
        emit(p, Instruction(Opcode.POP,  [_reg(R2)], comment=f"{name}: pop b"))
        emit(p, Instruction(Opcode.POP,  [_reg(R1)], comment=f"{name}: pop a"))
        emit(p, Instruction(Opcode.CMP,  [_reg(R1), _reg(R2)], am=0,
                            comment=f"{name}: CMP a, b"))
        emit(p, Instruction(opcode_branch, [_lbl(lbl_true)],
                            comment=f"{name}: branch if true"))
        # false
        emit(p, Instruction(Opcode.LUI,  [_reg(R1), _imm(0)], comment=f"{name}: false=0"))
        emit(p, Instruction(Opcode.ADD,  [_reg(R1), _reg(R1), _imm(0)], am=1))
        emit(p, Instruction(Opcode.JMP,  [_lbl(lbl_end)], comment=f"{name}: skip true"))
        p.labels[lbl_true] = len(p.instructions)
        # true -> 1  (язык использует 1, не -1, согласно спецификации)
        emit(p, Instruction(Opcode.LUI,  [_reg(R1), _imm(0)], comment=f"{name}: true=1"))
        emit(p, Instruction(Opcode.ADD,  [_reg(R1), _reg(R1), _imm(1)], am=1))
        p.labels[lbl_end] = len(p.instructions)
        emit(p, Instruction(Opcode.PUSH, [_reg(R1)], comment=f"{name}: push flag"))
    return _impl

def _bi_fetch(p: Program):
    # @ ( addr -- val )
    emit(p, Instruction(Opcode.POP, [_reg(R1)], comment="@ pop addr"))
    emit(p, Instruction(Opcode.LD,  [_reg(R1), _reg(R1)], am=1, comment="@ LD R1=[R1]"))
    emit(p, Instruction(Opcode.PUSH,[_reg(R1)], comment="@ push val"))

def _bi_store(p: Program):
    # ! ( val addr -- )
    emit(p, Instruction(Opcode.POP, [_reg(R1)], comment="! pop addr"))
    emit(p, Instruction(Opcode.POP, [_reg(R2)], comment="! pop val"))
    emit(p, Instruction(Opcode.ST,  [_reg(R2), _reg(R1)], am=1, comment="! ST [R1]=R2"))

def _bi_in(p: Program):
    # IN ( port_num -- val )
    emit(p, Instruction(Opcode.POP, [_reg(R1)], comment="IN: pop port"))
    emit(p, Instruction(Opcode.IN,  [_reg(R1), _imm(0)], comment="IN: IN R1, #0"))
    emit(p, Instruction(Opcode.PUSH,[_reg(R1)], comment="IN: push val"))

def _bi_out(p: Program):
    # OUT ( val port_num -- )
    emit(p, Instruction(Opcode.POP, [_reg(R2)], comment="OUT: pop port_num"))
    emit(p, Instruction(Opcode.POP, [_reg(R1)], comment="OUT: pop val"))
    emit(p, Instruction(Opcode.OUT,  [_reg(R1), _imm(1)], comment="OUT: OUT R1, #1"))

def _bi_halt(p: Program):
    emit(p, Instruction(Opcode.HLT, [], comment="HALT"))

_BUILTINS = {
    "DUP":     _bi_dup,
    "DROP":    _bi_drop,
    "SWAP":    _bi_swap,
    "OVER":    _bi_over,
    "ROT":     _bi_rot,
    "-ROT":    _bi_nrot,
    "TUCK":    _bi_tuck,
    "+":       _bi_add,
    "-":       _bi_sub,
    "*":       _bi_mul,
    "/":       _bi_div,
    "MOD":     _bi_mod,
    "=":       _bi_cmp_op(Opcode.BEQ, "EQ"),
    "<":       _bi_cmp_op(Opcode.BLT, "LT"),
    ">":       _bi_cmp_op(Opcode.BGT, "GT"),
    "@":       _bi_fetch,
    "!":       _bi_store,
    "IN":      _bi_in,
    "OUT":     _bi_out,
    "HALT":    _bi_halt,
}

def translate_program(tokens: List[Token], result: Program) -> None:
    """Основная точка входа транслятора."""
    global _label_counter
    _label_counter = itertools.count()   # сброс счётчика для детерминизма
    t = Translator(tokens, result)
    t.translate()