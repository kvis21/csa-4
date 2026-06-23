from translator.translator import Program


def parse_schedule(content: str):
    """парсер файла расписания ввода."""
    schedule = []
    if not content:
        return schedule

    for line in content.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
            
        parts = line.split(None, 1)
        if len(parts) < 2: 
            assert SyntaxError("Invalid schedule format")

        tick = int(parts[0])
        val_str = parts[1].strip()
        
        if (val_str.startswith("'") and val_str.endswith("'")) or \
           (val_str.startswith('"') and val_str.endswith('"')):
            inner_char = val_str[1:2] if len(val_str) > 2 else 0
            char_code = ord(inner_char)
        elif val_str.lower().startswith("0x"):
            char_code = int(val_str, 16)
        elif val_str.lstrip("-").isdigit():
            char_code = int(val_str)
        else:
            char_code = ord(val_str)
        schedule.append((tick, char_code))
    return schedule


def build_hex_dump(program: Program, machine_code: list[str]) -> str:
    """Формирует человеко-читаемый дамп скомпилированной программы."""
    lines = []
    lines.append("=== Instruction Memory (IMEM) ===")

    for i, (bin_str, instr) in enumerate(zip(machine_code, program.instructions)):
        hex_val = f"0x{int(bin_str, 2):08X}"
        lines.append(f"{i:04X} - {hex_val} - {instr}")

    if program.data_memory:
        lines.append("\n=== Data Memory (DMEM) ===")
        for i, val in enumerate(program.data_memory):
            hex_val = f"0x{val & 0xFFFFFFFF:08X}"
            char_repr = repr(chr(val)) if 32 <= val <= 126 else "'.'"
            lines.append(f"{i:04X} - {hex_val} - {val} ({char_repr})")

    return "\n".join(lines)


if __name__ == "__main__":
    print(parse_schedule("""    1 t
  2 e
  3 s
  4 t
  5 '9'S
  6 0x31
  7 '-1'
  10 10
  12 '0'"""))