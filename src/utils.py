from src.translator.translator import Program
import struct
import sys

type ScheduleType = list[tuple[int, int]]


def parse_schedule(content: str) -> ScheduleType:
    """парсер файла расписания ввода."""
    schedule: list[tuple[int, int]] = []
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

        if (val_str.startswith("'") and val_str.endswith("'")) or (val_str.startswith('"') and val_str.endswith('"')):
            inner_char = val_str[1:2] if len(val_str) > 2 else '\0'
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
        lines.append(f"{i:04} - {hex_val} - {instr}")

    if program.data_memory:
        lines.append("\n=== Data Memory (DMEM) ===")
        for i, val in enumerate(program.data_memory):
            hex_val = f"0x{val & 0xFFFFFFFF:08X}"
            char_repr = repr(chr(val)) if 32 <= val <= 126 else "'.'"
            lines.append(f"{i:04} - {hex_val} - {val} ({char_repr})")

    return "\n".join(lines)


def load_binary(filename: str) -> list[int]:
    memory: list[int] = []
    with open(filename, "rb") as f:
        while chunk := f.read(4):
            if len(chunk) == 4:
                val = struct.unpack(">I", chunk)[0]
                memory.append(val)
    return memory


def run_simulation(imem_file: str,
                   dmem_file: str,
                   schedule: ScheduleType,
                   trace_file: str = "") -> list[int]:
    from src.machine import DataPath, ControlUnit

    imem = load_binary(imem_file)
    dmem = load_binary(dmem_file)

    imem += [0] * (1024 - len(imem))
    dmem += [0] * (2048 - len(dmem))

    dp = DataPath(dmem_size=2048, imem_size=1024, input_schedule=schedule)

    dp.imem = imem
    dp.dmem = dmem

    with open(trace_file, "w", encoding="utf-8") if trace_file else sys.stdout as log_output :
        cu = ControlUnit(dp, log_output)
        limit = 100000
        while not cu.halted and cu.tick_count < limit:
            cu.tick()
    return dp.out_buffer
