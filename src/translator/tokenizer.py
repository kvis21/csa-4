# translator/tokenizer.py
import re
from enum import Enum, auto
from dataclasses import dataclass


class TokenType(Enum):
    WORD = auto()
    NUMBER = auto()
    STRING = auto()


@dataclass
class Token:
    type: TokenType
    value: str
    line: int
    column: int

    def __repr__(self) -> str:
        return f"Token({self.type.name}, '{self.value}', line={self.line}, col={self.column})"


class Tokenizer:
    @staticmethod
    def tokenize(source_code: str) -> list[Token]:
        tokens = []
        lines = source_code.split("\n")

        pattern = r'(P"[^"]*")|(-?\d+)|([^\s\\]+)'

        for line_idx, line in enumerate(lines):
            line_num = line_idx + 1

            clean_line = re.split(r"\\", line)[0]

            matches = re.finditer(pattern, clean_line)

            for match in matches:
                value = match.group(0)
                col = match.start() + 1

                if value.startswith('P"'):
                    token_type = TokenType.STRING
                elif value.lstrip("-").isdigit():
                    token_type = TokenType.NUMBER
                else:
                    token_type = TokenType.WORD

                tokens.append(Token(token_type, value, line_num, col))

        return tokens
