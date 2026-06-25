from enum import Enum, StrEnum
from dataclasses import dataclass, field
from typing import Any

class Opcode(int, Enum):
    LUI = 0x00
    LD = 0x01
    ST = 0x02

    ADD = 0x11
    SUB = 0x12
    MUL = 0x13
    DIV = 0x14
    MOD = 0x15
    CMP = 0x16

    JMP = 0x20
    BEQ = 0x21
    BNE = 0x22
    BGT = 0x23
    BLT = 0x24
    CALL = 0x30
    RET = 0x31
    PUSH = 0x32
    POP = 0x33

    IN = 0x40
    OUT = 0x41

    EI = 0x42
    DI = 0x43
    IRET = 0x44
    HLT = 0x45


class Register(int, Enum):
    R0 = 0
    R1 = 1
    R2 = 2
    R3 = 3
    R4 = 4
    R5 = 5
    R6 = 6
    R7 = 7


class ArgType(StrEnum):
    REG = "REG"
    IMM = "IMM"
    ADDR = "ADDR"
    LABEL = "LABEL"


@dataclass
class Arg:
    """Аргумент инструкции."""
    value: int | str | Register
    arg_type: ArgType

    def to_dict(self) -> dict[str, Any]:
        val = self.value.value if isinstance(self.value, Register) else self.value
        return {"value": val, "type": self.arg_type.value}


@dataclass
class Instruction:
    opcode: Opcode
    args: list[Arg] = field(default_factory=list)
    am: int | None = None
    comment: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Сериализация инструкции для генерации объектного файла."""
        res: dict[str, Any] = {
            "opcode": self.opcode.name,
            "args": [arg.to_dict() for arg in self.args],
        }
        if self.am is not None:
            res["am"] = self.am
        if self.comment:
            res["comment"] = self.comment
        return res

    def __str__(self) -> str:
        formatted_args = []
        for a in self.args:
            if a.arg_type == ArgType.REG:
                formatted_args.append(f"R{int(a.value)}")
            elif a.arg_type == ArgType.IMM:
                formatted_args.append(f"#{a.value}")
            else:
                formatted_args.append(str(a.value))

        args_str = ", ".join(formatted_args)
        base = f"{self.opcode.name:<5} {args_str}"

        if self.comment:
            return f"{base:<30} ; {self.comment}"
        return base
