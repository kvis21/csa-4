from translator.translator import Program

"""def parse_schedule(content: str):
    schedule = []
    for line in content.strip().split("\n"):
        if line.strip():
            parts = line.strip().split()
            if len(parts) >= 2:
                schedule.append((int(parts[0]), parts[1]))
    return schedule"""
        
def parse_schedule(content: str):
    """Надежный парсер файла расписания ввода."""
    schedule = []
    if not content:
        return schedule
        
    for line in content.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) == 2:
            tick = int(parts[0])
            val_str = parts[1].strip()
            try:
                char_code = int(val_str)
                char = chr(char_code)
            except ValueError:
                if val_str == "\\n":
                    char = "\n"
                elif val_str == "\\t":
                    char = "\t"
                elif len(val_str) > 0:
                    char = val_str[0]  
                else:
                    char = "\x00" 
            schedule.append((tick, char))
        elif len(parts) == 1:
            tick = int(parts[0])
            schedule.append((tick, "\x00"))
                
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

