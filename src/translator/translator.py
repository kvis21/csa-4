from dataclasses import dataclass, field
import itertools

from isa import Opcode, Instruction, Arg, ArgType, Register
from translator.tokenizer import Token, TokenType

_label_counter = itertools.count()


def _uid() -> str:
    return str(next(_label_counter))


@dataclass
class Program:
    """Представление скомпилированной программы."""

    instructions: list[Instruction] = field(default_factory=list)
    data_memory: list[int] = field(default_factory=list)

    labels: dict[str, int] = field(default_factory=dict) 
    variables: dict[str, int] = field(default_factory=dict) 

    isr_table: dict[int, int] = field(default_factory=dict)

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
    def to_machine_code(self) -> list[str]:
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
            rd = val(instr.args[0])
            imm = val(instr.args[1]) & 0x3FFFFF
            word = (opc << 25) | (rd << 22) | imm

        elif instr.opcode in (Opcode.ADD, Opcode.SUB, Opcode.MUL, Opcode.DIV, Opcode.MOD, Opcode.CMP):
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

        elif instr.opcode in (Opcode.JMP, Opcode.BEQ, Opcode.BNE, Opcode.BGT, Opcode.BLT, Opcode.CALL):
            addr = val(instr.args[0]) & 0x1FFFFFF
            word = (opc << 25) | addr

        elif instr.opcode in (Opcode.IN, Opcode.OUT):
            reg = val(instr.args[0])
            port = val(instr.args[1]) & 0x3FFFFF
            word = (opc << 25) | (reg << 22) | port

        elif instr.opcode in (Opcode.PUSH, Opcode.POP):
            reg = val(instr.args[0])
            word = (opc << 25) | (reg << 22)

        elif instr.opcode in (Opcode.RET, Opcode.EI, Opcode.DI, Opcode.IRET, Opcode.HLT):
            word = opc << 25

        return f"{word:032b}"


R0 = Register.R0
R1 = Register.R1
R2 = Register.R2
R3 = Register.R3
R4 = Register.R4
R5 = Register.R5
R6 = Register.R6
R7 = Register.R7


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
    """Загрузить константу на стек с учетом кэширования R4/R5."""
    upper = (val >> 10) & 0x3FFFFF
    lower = val & 0x3FF
    
    # Сдвигаем стек вниз: старый NOS уходит в память, TOS становится NOS
    emit(p, Instruction(Opcode.PUSH, [_reg(R5)], comment="save NOS to mem"))
    emit(p, Instruction(Opcode.ADD, [_reg(R5), _reg(R4), _imm(0)], am=1, comment="TOS -> NOS"))
    
    # Пишем новое значение прямо в TOS (R4)
    emit(p, Instruction(Opcode.LUI, [_reg(R4), _imm(upper)], comment=comment or f"LUI #{upper} (const {val})"))
    emit(p, Instruction(Opcode.ADD, [_reg(R4), _reg(R4), _imm(lower)], am=1, comment=f"ADD #{lower} (const {val})"))


def _push_label(p: Program, lbl: str, comment: str = "") -> None:
    """Положить адрес метки на стек с учетом кэширования R4/R5."""
    emit(p, Instruction(Opcode.PUSH, [_reg(R5)], comment="save NOS to mem"))
    emit(p, Instruction(Opcode.ADD, [_reg(R5), _reg(R4), _imm(0)], am=1, comment="TOS -> NOS"))
    
    emit(p, Instruction(Opcode.LUI, [_reg(R4), _lbl(f"__lui__{lbl}")], comment=comment or f"LUI addr({lbl})"))
    emit(p, Instruction(Opcode.ADD, [_reg(R4), _reg(R4), _lbl(f"__low__{lbl}")], am=1, comment=f"ADD low addr({lbl})"))

class Translator:
    def __init__(self, tokens: list[Token], program: Program):
        self.tokens = tokens
        self.pos = 0
        self.program = program

    def peek(self) -> Token | None:
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
            raise SyntaxError(f"Строка {t.line}: ожидалось '{value}', получено '{t.value}'")
        return t

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

    def _translate_word(self) -> None:
        t = self.peek()
        if t is None:
            return
        w = t.value
        wu = w.upper()

        if wu == "MAIN" and self.pos == self.pos:
            self.consume()
            return

        if wu == "VARIABLE":
            self.consume()
            name_tok = self.consume()
            addr = self.program.allocate_variable(0)
            self.program.variables[name_tok.value] = addr
            return

        if w == ":":
            self.consume()
            name_tok = self.consume()
            name = name_tok.value
            self.program.labels[name] = len(self.program.instructions)

            while self.pos < len(self.tokens) and self.peek().value != ";":
                self._translate_word()
            self.expect(";")
            emit(self.program, Instruction(Opcode.RET, [], comment=f"RET from {name}"))
            return

        if t.type == TokenType.STRING:
            self.consume()
            text = w[2:-1]
            addr = self.program.allocate_string(text)
            _push_const(self.program, addr, f'PUSH addr of pstr "{text}"')
            return

        if t.type == TokenType.NUMBER:
            self.consume()
            _push_const(self.program, int(w), f"PUSH {w}")
            return

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

        if w == "'":
            self.consume()
            name_tok = self.consume()
            _push_label(self.program, name_tok.value, comment=f"tick: push xt of {name_tok.value}")
            return

        if wu == "EXECUTE":
            self.consume()
            self._emit_execute()
            return

        if wu in _BUILTINS:
            self.consume()
            _BUILTINS[wu](self.program)
            return

        if w in self.program.variables:
            self.consume()
            addr = self.program.variables[w]
            _push_const(self.program, addr, f"PUSH addr({w})")
            return

        if wu == "MAIN" and w == "MAIN":
            self.consume()
            self.program.labels["MAIN"] = len(self.program.instructions)
            return

        self.consume()
        emit(self.program, Instruction(Opcode.CALL, [_lbl(w)], comment=f"CALL {w}"))

    def _translate_if(self) -> None:
        p = self.program
        uid = _uid()

        emit(p, Instruction(Opcode.ADD, [_reg(R1), _reg(R4), _imm(0)], am=1, comment="IF: save flag to R1"))
        emit(p, Instruction(Opcode.ADD, [_reg(R4), _reg(R5), _imm(0)], am=1, comment="IF: TOS = NOS"))
        emit(p, Instruction(Opcode.POP, [_reg(R5)], comment="IF: pop new NOS"))
        emit(p, Instruction(Opcode.CMP, [_reg(R1), _reg(R0)], am=0, comment="IF: CMP saved flag with 0"))

        lbl_else = f"__else_{uid}"
        emit(p, Instruction(Opcode.BEQ, [_lbl(lbl_else)], comment="IF: BEQ to else/then"))

        while self.pos < len(self.tokens):
            nw = self.peek().value.upper()
            if nw in ("ELSE", "THEN"):
                break
            self._translate_word()

        lbl_end = f"__then_{uid}"

        if self.peek() and self.peek().value.upper() == "ELSE":
            self.consume()
            emit(p, Instruction(Opcode.JMP, [_lbl(lbl_end)], comment="IF: JMP over ELSE"))
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

    def _translate_begin(self) -> None:
        p = self.program
        uid = _uid()
        lbl_begin = f"__begin_{uid}"
        p.labels[lbl_begin] = len(p.instructions)

        while self.pos < len(self.tokens):
            nw = self.peek().value.upper()
            if nw in ("WHILE", ):
                break
            self._translate_word()

        nw = self.peek().value.upper() if self.peek() else ""

        if nw == "WHILE":
            self.consume()
            emit(p, Instruction(Opcode.ADD, [_reg(R1), _reg(R4), _imm(0)], am=1, comment="WHILE: save flag to R1"))
            emit(p, Instruction(Opcode.ADD, [_reg(R4), _reg(R5), _imm(0)], am=1, comment="WHILE: TOS = NOS"))
            emit(p, Instruction(Opcode.POP, [_reg(R5)], comment="WHILE: pop new NOS"))
            emit(p, Instruction(Opcode.CMP, [_reg(R1), _reg(R0)], am=0, comment="WHILE: CMP saved flag with 0"))

            lbl_repeat_end = f"__repeat_{uid}"
            emit(p, Instruction(Opcode.BEQ, [_lbl(lbl_repeat_end)], comment="WHILE: BEQ exit loop if false"))

            while self.pos < len(self.tokens):
                nw2 = self.peek().value.upper()
                if nw2 == "REPEAT":
                    break
                self._translate_word()

            self.expect("REPEAT")
            emit(p, Instruction(Opcode.JMP, [_lbl(lbl_begin)], comment="REPEAT: JMP back to BEGIN"))
            p.labels[lbl_repeat_end] = len(p.instructions)

    def _translate_do(self) -> None:
        p = self.program
        uid = _uid()

        lbl_i = f"__do_i_{uid}"
        lbl_limit = f"__do_limit_{uid}"
        addr_i = p.allocate_variable(0)
        addr_limit = p.allocate_variable(0)
        p.variables[lbl_i] = addr_i
        p.variables[lbl_limit] = addr_limit

        emit(p, Instruction(Opcode.ST, [_reg(R4), _addr(addr_i)], am=0, comment="DO: store start(TOS) -> I"))
        emit(p, Instruction(Opcode.ST, [_reg(R5), _addr(addr_limit)], am=0, comment="DO: store limit(NOS) -> LIMIT"))
        emit(p, Instruction(Opcode.POP, [_reg(R4)], comment="DO: pop new TOS"))
        emit(p, Instruction(Opcode.POP, [_reg(R5)], comment="DO: pop new NOS"))

        lbl_do_top = f"__do_top_{uid}"
        lbl_do_end = f"__do_end_{uid}"
        p.labels[lbl_do_top] = len(p.instructions)

        emit(p, Instruction(Opcode.LD, [_reg(R1), _addr(addr_i)], am=0, comment="DO: load I"))
        emit(p, Instruction(Opcode.LD, [_reg(R2), _addr(addr_limit)], am=0, comment="DO: load LIMIT"))
        emit(p, Instruction(Opcode.CMP, [_reg(R1), _reg(R2)], am=0, comment="DO: CMP I, LIMIT"))
        emit(p, Instruction(Opcode.BEQ, [_lbl(lbl_do_end)], comment="DO: exit if I == LIMIT"))
        emit(p, Instruction(Opcode.BGT, [_lbl(lbl_do_end)], comment="DO: exit if I > LIMIT"))

        while self.pos < len(self.tokens):
            nw = self.peek().value.upper()
            if nw == "LOOP":
                break
            if nw == "I" and self.peek().value == "I":
                self.consume()
                emit(p, Instruction(Opcode.LD, [_reg(R1), _addr(addr_i)], am=0, comment="I: load loop counter"))
                emit(p, Instruction(Opcode.PUSH, [_reg(R5)], comment="I: save NOS"))
                emit(p, Instruction(Opcode.ADD, [_reg(R5), _reg(R4), _imm(0)], am=1, comment="I: TOS->NOS"))
                emit(p, Instruction(Opcode.ADD, [_reg(R4), _reg(R1), _imm(0)], am=1, comment="I: TOS=R1"))
                continue
            self._translate_word()
        self.expect("LOOP")

        emit(p, Instruction(Opcode.LD, [_reg(R1), _addr(addr_i)], am=0, comment="LOOP: load I"))
        emit(p, Instruction(Opcode.ADD, [_reg(R1), _reg(R1), _imm(1)], am=1, comment="LOOP: I++"))
        emit(p, Instruction(Opcode.ST, [_reg(R1), _addr(addr_i)], am=0, comment="LOOP: store I"))
        emit(p, Instruction(Opcode.JMP, [_lbl(lbl_do_top)], comment="LOOP: JMP back"))
        p.labels[lbl_do_end] = len(p.instructions)

    def _emit_set_isr(self) -> None:
        p = self.program
        if "__isr_table__" not in p.variables:
            base = len(p.data_memory)
            for _ in range(8):
                p.data_memory.append(0)
            p.variables["__isr_table__"] = base
        base = p.variables["__isr_table__"]

        # xt in NOS(R5), vector_num in TOS(R4)
        emit(p, Instruction(Opcode.ADD, [_reg(R2), _reg(R4), _imm(0)], am=1, comment="SET-ISR: vector_num = TOS"))
        emit(p, Instruction(Opcode.ADD, [_reg(R1), _reg(R5), _imm(0)], am=1, comment="SET-ISR: xt = NOS"))
        emit(p, Instruction(Opcode.ADD, [_reg(R3), _reg(R2), _imm(base)], am=1, comment="SET-ISR: R3 = base + vector"))
        emit(p, Instruction(Opcode.ST, [_reg(R1), _reg(R3)], am=1, comment="SET-ISR: mem[R3] = xt"))
        
        emit(p, Instruction(Opcode.POP, [_reg(R4)], comment="SET-ISR: pop new TOS"))
        emit(p, Instruction(Opcode.POP, [_reg(R5)], comment="SET-ISR: pop new NOS"))

    def _emit_execute(self) -> None:
        p = self.program
        if "__execute_trampoline__" not in p.labels:
            pass

        if "__exec_cell__" not in p.variables:
            p.variables["__exec_cell__"] = p.allocate_variable(0)

        cell = p.variables["__exec_cell__"]
        
        # xt is in TOS(R4)
        emit(p, Instruction(Opcode.ST, [_reg(R4), _addr(cell)], am=0, comment="EXECUTE: store xt(TOS)"))
        emit(p, Instruction(Opcode.ADD, [_reg(R4), _reg(R5), _imm(0)], am=1, comment="EXECUTE: TOS=NOS"))
        emit(p, Instruction(Opcode.POP, [_reg(R5)], comment="EXECUTE: pop new NOS"))
        
        emit(p, Instruction(Opcode.CALL, [_lbl("__execute_dispatch__")], comment="EXECUTE: call dispatch"))

    # Pass 2: линковка
    def _link(self) -> None:
        p = self.program

        if "__exec_cell__" in p.variables:
            self._generate_execute_dispatch()

        for instr in p.instructions:
            for arg in instr.args:
                if arg.arg_type == ArgType.LABEL:
                    name = arg.value
                    if name.startswith("__lui__"):
                        proc = name[len("__lui__") :]
                        real_addr = p.labels.get(proc, p.variables.get(proc, 0))
                        arg.arg_type = ArgType.IMM
                        arg.value = (real_addr >> 10) & 0x3FFFFF
                    elif name.startswith("__low__"):
                        proc = name[len("__low__") :]
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

        emit(p, Instruction(Opcode.LD, [_reg(R4), _addr(cell)], am=0, comment="EXEC_DISP: load xt"))

        lbl_disp_end = "__exec_disp_end__"

        for proc_name, proc_addr in list(p.labels.items()):
            if proc_name.startswith("__"):
                continue
            uid = _uid()
            lbl_no_match = f"__exec_no_{uid}"
            upper = (proc_addr >> 10) & 0x3FFFFF
            lower = proc_addr & 0x3FF
            emit(p, Instruction(Opcode.LUI, [_reg(R3), _imm(upper)], comment=f"DISP: load addr of {proc_name} upper"))
            emit(
                p,
                Instruction(
                    Opcode.ADD, [_reg(R3), _reg(R3), _imm(lower)], am=1, comment=f"DISP: load addr of {proc_name} lower"
                ),
            )
            emit(p, Instruction(Opcode.CMP, [_reg(R4), _reg(R3)], am=0, comment=f"DISP: CMP xt == {proc_name}?"))
            emit(p, Instruction(Opcode.BNE, [_lbl(lbl_no_match)], comment=f"DISP: BNE skip {proc_name}"))
            emit(p, Instruction(Opcode.CALL, [_addr(proc_addr)], comment=f"DISP: CALL {proc_name}"))
            emit(p, Instruction(Opcode.RET, [], comment="DISP: RET after dispatch"))
            p.labels[lbl_no_match] = len(p.instructions)

            emit(p, Instruction(Opcode.RET, [], comment="EXEC_DISP: no match, RET"))
        p.labels[lbl_disp_end] = len(p.instructions)


def _bi_dup(p: Program) -> None:
    # DUP ( a -- a a )
    emit(p, Instruction(Opcode.PUSH, [_reg(R5)], comment="DUP: save NOS to mem"))
    emit(p, Instruction(Opcode.ADD, [_reg(R5), _reg(R4), _imm(0)], am=1, comment="DUP: NOS = TOS"))


def _bi_drop(p: Program) -> None:
    # DROP ( a -- )
    emit(p, Instruction(Opcode.ADD, [_reg(R4), _reg(R5), _imm(0)], am=1, comment="DROP: TOS = NOS"))
    emit(p, Instruction(Opcode.POP, [_reg(R5)], comment="DROP: pop new NOS from mem"))


def _bi_swap(p: Program) -> None:
    # SWAP ( a b -- b a )
    emit(p, Instruction(Opcode.ADD, [_reg(R1), _reg(R4), _imm(0)], am=1, comment="SWAP: tmp = TOS"))
    emit(p, Instruction(Opcode.ADD, [_reg(R4), _reg(R5), _imm(0)], am=1, comment="SWAP: TOS = NOS"))
    emit(p, Instruction(Opcode.ADD, [_reg(R5), _reg(R1), _imm(0)], am=1, comment="SWAP: NOS = tmp"))


def _bi_over(p: Program) -> None:
    # OVER ( a b -- a b a )
    emit(p, Instruction(Opcode.PUSH, [_reg(R5)], comment="OVER: save old NOS(a) to mem"))
    emit(p, Instruction(Opcode.ADD, [_reg(R1), _reg(R5), _imm(0)], am=1, comment="OVER: tmp = NOS(b)"))
    emit(p, Instruction(Opcode.ADD, [_reg(R5), _reg(R4), _imm(0)], am=1, comment="OVER: NOS = TOS(a)"))
    emit(p, Instruction(Opcode.ADD, [_reg(R4), _reg(R1), _imm(0)], am=1, comment="OVER: TOS = tmp(b)"))


def _bi_rot(p: Program) -> None:
    # ROT ( c b a -- b a c ) -> Target: [SP]=b, NOS=a, TOS=c
    emit(p, Instruction(Opcode.POP, [_reg(R1)], comment="ROT: R1 = c (3rd from mem)"))
    emit(p, Instruction(Opcode.PUSH, [_reg(R5)], comment="ROT: mem[SP] = b (old NOS)"))
    emit(p, Instruction(Opcode.ADD, [_reg(R5), _reg(R4), _imm(0)], am=1, comment="ROT: NOS = a (old TOS)"))
    emit(p, Instruction(Opcode.ADD, [_reg(R4), _reg(R1), _imm(0)], am=1, comment="ROT: TOS = c"))


def _bi_nrot(p: Program) -> None:
    # -ROT ( c b a -- a c b ) -> Target: [SP]=a, NOS=c, TOS=b
    emit(p, Instruction(Opcode.POP, [_reg(R1)], comment="-ROT: R1 = c (3rd from mem)"))
    emit(p, Instruction(Opcode.PUSH, [_reg(R4)], comment="-ROT: mem[SP] = a (old TOS)"))
    emit(p, Instruction(Opcode.ADD, [_reg(R4), _reg(R5), _imm(0)], am=1, comment="-ROT: TOS = b (old NOS)"))
    emit(p, Instruction(Opcode.ADD, [_reg(R5), _reg(R1), _imm(0)], am=1, comment="-ROT: NOS = c"))


def _bi_tuck(p: Program) -> None:
    # TUCK ( a b -- b a b ) 
    emit(p, Instruction(Opcode.PUSH, [_reg(R4)], comment="TUCK: push TOS(b) under NOS(a)"))


def _bi_add(p: Program) -> None:
    emit(p, Instruction(Opcode.ADD, [_reg(R4), _reg(R5), _reg(R4)], am=0, comment="+: TOS = NOS + TOS"))
    emit(p, Instruction(Opcode.POP, [_reg(R5)], comment="+: pop new NOS"))


def _bi_sub(p: Program) -> None:
    emit(p, Instruction(Opcode.SUB, [_reg(R4), _reg(R5), _reg(R4)], am=0, comment="-: TOS = NOS - TOS"))
    emit(p, Instruction(Opcode.POP, [_reg(R5)], comment="-: pop new NOS"))


def _bi_mul(p: Program) -> None:
    emit(p, Instruction(Opcode.MUL, [_reg(R4), _reg(R5), _reg(R4)], am=0, comment="*: TOS = NOS * TOS"))
    emit(p, Instruction(Opcode.POP, [_reg(R5)], comment="*: pop new NOS"))


def _bi_div(p: Program) -> None:
    emit(p, Instruction(Opcode.DIV, [_reg(R4), _reg(R5), _reg(R4)], am=0, comment="/: TOS = NOS / TOS"))
    emit(p, Instruction(Opcode.POP, [_reg(R5)], comment="/: pop new NOS"))


def _bi_mod(p: Program) -> None:
    emit(p, Instruction(Opcode.MOD, [_reg(R4), _reg(R5), _reg(R4)], am=0, comment="MOD: TOS = NOS % TOS"))
    emit(p, Instruction(Opcode.POP, [_reg(R5)], comment="MOD: pop new NOS"))


def _bi_cmp_op(opcode_branch: Opcode, name: str):
    """Фабрика: ( a b -- 1/0 ) через CMP + ветвление."""
    def _impl(p: Program) -> None:
        uid = _uid()
        lbl_true = f"__{name}_t_{uid}"
        lbl_end = f"__{name}_e_{uid}"
        
        emit(p, Instruction(Opcode.CMP, [_reg(R5), _reg(R4)], am=0, comment=f"{name}: CMP NOS, TOS"))
        emit(p, Instruction(opcode_branch, [_lbl(lbl_true)], comment=f"{name}: branch if true"))
        emit(p, Instruction(Opcode.ADD, [_reg(R4), _reg(R0), _imm(0)], am=1, comment=f"{name}: TOS = 0 (False)"))
        emit(p, Instruction(Opcode.JMP, [_lbl(lbl_end)], comment=f"{name}: skip true"))
        p.labels[lbl_true] = len(p.instructions)
        emit(p, Instruction(Opcode.ADD, [_reg(R4), _reg(R0), _imm(1)], am=1, comment=f"{name}: TOS = 1 (True)"))
        p.labels[lbl_end] = len(p.instructions)
        emit(p, Instruction(Opcode.POP, [_reg(R5)], comment=f"{name}: pop new NOS"))
    return _impl


def _bi_fetch(p: Program) -> None:
    # @ ( addr -- val )
    # Адрес лежит в R4. Результат кладем туда же. NOS не трогаем.
    emit(p, Instruction(Opcode.LD, [_reg(R4), _reg(R4)], am=1, comment="@ LD TOS=[TOS]"))


def _bi_store(p: Program) -> None:
    # ! ( val addr -- )
    emit(p, Instruction(Opcode.ST, [_reg(R5), _reg(R4)], am=1, comment="! ST [TOS]=NOS"))
    emit(p, Instruction(Opcode.POP, [_reg(R4)], comment="! pop new TOS"))
    emit(p, Instruction(Opcode.POP, [_reg(R5)], comment="! pop new NOS"))


def _bi_in(p: Program):
    # IN ( port -- val )
    emit(p, Instruction(Opcode.IN, [_reg(R4), _imm(0)], comment="IN: IN TOS, #0"))

def _bi_out(p: Program):
    # OUT ( val port -- )
    emit(p, Instruction(Opcode.OUT, [_reg(R5), _imm(1)], comment="OUT: OUT NOS, #1"))
    emit(p, Instruction(Opcode.POP, [_reg(R4)], comment="OUT: pop new TOS"))
    emit(p, Instruction(Opcode.POP, [_reg(R5)], comment="OUT: pop new NOS"))


def _bi_halt(p: Program) -> None:
    emit(p, Instruction(Opcode.HLT, [], comment="HALT"))


_BUILTINS = {
    "DUP": _bi_dup,
    "DROP": _bi_drop,
    "SWAP": _bi_swap,
    "OVER": _bi_over,
    "ROT": _bi_rot,
    "-ROT": _bi_nrot,
    "TUCK": _bi_tuck,
    "+": _bi_add,
    "-": _bi_sub,
    "*": _bi_mul,
    "/": _bi_div,
    "MOD": _bi_mod,
    "=": _bi_cmp_op(Opcode.BEQ, "EQ"),
    "<": _bi_cmp_op(Opcode.BLT, "LT"),
    ">": _bi_cmp_op(Opcode.BGT, "GT"),
    "@": _bi_fetch,
    "!": _bi_store,
    "IN": _bi_in,
    "OUT": _bi_out,
    "HALT": _bi_halt,
}


def translate_program(tokens: list[Token], result: Program) -> None:
    """Основная точка входа транслятора."""
    global _label_counter
    _label_counter = itertools.count()  
    t = Translator(tokens, result)
    t.translate()
