# translator/tokenizer.py
import re
from enum import Enum, auto
from dataclasses import dataclass
from typing import List

class TokenType(Enum):
    """Типы токенов для Forth-подобного языка."""
    WORD   = auto()  # Команды, метки, переменные
    NUMBER = auto()  # Целочисленные литералы
    STRING = auto()  # Pascal-строки формата P"..."

@dataclass
class Token:
    """Класс представления токена."""
    type: TokenType
    value: str
    line: int
    column: int

    def __repr__(self) -> str:
        return f"Token({self.type.name}, '{self.value}', line={self.line}, col={self.column})"

class Tokenizer:
    """Лексический анализатор (сканер текста программы)."""
    
    @staticmethod
    def tokenize(source_code: str) -> List[Token]:
        tokens = []
        lines = source_code.split('\n')
        
        # Регулярка:
        # 1. P"[^"]*"  -> Pascal-строки
        # 2. -?\d+      -> Числа (включая отрицательные)
        # 3. [^\s\\]+   -> Любые слова (кроме пробелов и начала комментария \)
        pattern = r'(P"[^"]*")|(-?\d+)|([^\s\\]+)'
        
        for line_idx, line in enumerate(lines):
            line_num = line_idx + 1
            
            # Удаляем комментарии (от начала \ до конца строки)
            clean_line = re.split(r'\\', line)[0]
            
            matches = re.finditer(pattern, clean_line)
            
            for match in matches:
                value = match.group(0)
                col = match.start() + 1
                
                # Определение типа
                if value.startswith('P"'):
                    token_type = TokenType.STRING
                elif value.lstrip('-').isdigit():
                    token_type = TokenType.NUMBER
                else:
                    token_type = TokenType.WORD
                
                tokens.append(Token(token_type, value, line_num, col))
        
        return tokens