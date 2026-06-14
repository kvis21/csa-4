from enum import Enum
from dataclasses import dataclass, field
from typing import List, Union, Optional

class Opcode(int, Enum):
    """Список опкодов команд процессора согласно спецификации.
    
    Каждая команда при бинарном кодировании занимает старшие 7 бит [31:25].
    """
    # Память и константы
    LUI  = 0x00  # Rd <- imm << 10
    LD   = 0x01  # Rd <- mem[Rs] или Rd <- mem[#addr]
    ST   = 0x02  # mem[Rs] <- Rd или mem[#addr] <- Rd
    
    # Арифметика и логика (АЛУ)
    ADD  = 0x11  # Rd <- Rs1 + Rs2  или  Rd <- Rs1 + #imm
    SUB  = 0x12  # Rd <- Rs1 - Rs2  или  Rd <- Rs1 - #imm
    MUL  = 0x13  # Rd <- Rs1 * Rs2  или  Rd <- Rs1 * #imm
    DIV  = 0x14  # Rd <- Rs1 / Rs2  или  Rd <- Rs1 / #imm
    MOD  = 0x15  # Rd <- Rs1 % Rs2  или  Rd <- Rs1 % #imm
    CMP  = 0x16  # SR.N, SR.Z <- Rs1 - Rs2  или  Rs1 - #imm
    
    # Ветвления (Формат переходов с абсолютным 25-битным адресом)
    JMP  = 0x20  # PC <- addr
    BEQ  = 0x21  # PC <- addr if Z=1
    BNE  = 0x22  # PC <- addr if Z=0
    BGT  = 0x23  # PC <- addr if Z=0 and N=0
    BLT  = 0x24  # PC <- addr if N=1
    
    # Процедуры и стек
    CALL = 0x30  # mem[RP] <- PC + 1; RP <- RP + 1; PC <- addr
    RET  = 0x31  # RP <- RP - 1; PC <- mem[RP]
    PUSH = 0x32  # mem[SP] <- Rs; SP <- SP + 1
    POP  = 0x33  # SP <- SP - 1; Rd <- mem[SP]
    
    # Ввод-вывод и прерывания
    IN   = 0x40  # Rd <- port[#port]
    OUT  = 0x41  # port[#port] <- Rs
    EI   = 0x42  # SR.IE <- 1
    DI   = 0x43  # SR.IE <- 0
    IRET = 0x44  # Возврат из прерывания (восстановление контекста)

class Register(int, Enum):
    """Список доступных регистров процессора (3 бита -> 8 регистров)."""
    R0 = 0  # Часто используется как Hardwired Zero
    R1 = 1
    R2 = 2
    R3 = 3
    R4 = 4
    R5 = 5
    R6 = 6
    R7 = 7

class ArgType(str, Enum):
    """Типы аргументов для транслятора и линкера."""
    REG   = "REG"     # Регистр общего назначения (0-7)
    IMM   = "IMM"     # Непосредственное значение (константа)
    ADDR  = "ADDR"    # Абсолютный адрес памяти / номер порта
    LABEL = "LABEL"   # Текстовая метка (разрешается транслятором в ADDR)

@dataclass
class Arg:
    """Аргумент инструкции."""
    value: Union[int, str, Register]
    arg_type: ArgType

    def to_dict(self) -> dict:
        """Сериализация аргумента для JSON-представления."""
        val = self.value.value if isinstance(self.value, Register) else self.value
        return {
            "value": val,
            "type": self.arg_type.value
        }

@dataclass
class Instruction:
    """Представление одной машинной инструкции."""
    opcode: Opcode
    args: List[Arg] = field(default_factory=list)
    am: Optional[int] = None  # Addressing Mode: 0 или 1 для команд памяти/АЛУ, где это применимо
    comment: str = ""

    def to_dict(self) -> dict:
        """Сериализация инструкции для генерации объектного файла."""
        res = {
            "opcode": self.opcode.name,
            "args": [arg.to_dict() for arg in self.args],
        }
        if self.am is not None:
            res["am"] = self.am
        if self.comment:
            res["comment"] = self.comment
        return res

    def __str__(self) -> str:
        """Текстовое представление инструкции (Disassembly) для логов и отладки."""
        formatted_args = []
        for a in self.args:
            if a.arg_type == ArgType.REG:
                formatted_args.append(f"R{int(a.value)}")
            elif a.arg_type == ArgType.IMM:
                formatted_args.append(f"#{a.value}")
            else:
                formatted_args.append(str(a.value))

        args_str = ", ".join(formatted_args)
        # Добавляем отображение режима адресации, если он явно задан
        am_str = f" [AM={self.am}]" if self.am is not None else ""
        base = f"{self.opcode.name:<5} {args_str}{am_str}"
        
        if self.comment:
            return f"{base:<30} ; {self.comment}"
        return base