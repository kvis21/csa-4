from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parent
PROJECT_ROOT = ROOT.parent
GOLDEN_ROOT = ROOT / "golden"

sys.path.insert(0, str(PROJECT_ROOT))

from src.translator.tokenizer import Tokenizer
from src.translator.translator import Program, translate_program
from src.utils import build_hex_dump, parse_schedule
from src.machine import DataPath, ControlUnit


# Кастомные классы-маркеры
class LiteralStr(str):
    pass

class FlowList(list):
    """list subclass that yaml.safe_dump emits as flow style."""

class LiteralStripStr(str):
    pass

class CustomDumper(yaml.SafeDumper):
    pass


def _literal_str_representer(dumper, data):
    return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')


def _flow_list_repr(dumper, data):
    return dumper.represent_sequence('tag:yaml.org,2002:seq', data, flow_style=True)

def _literal_strip_str_representer(dumper, data):
    return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|-')


def _str_representer(dumper, data):
    if '\n' in data:
        return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')
    return dumper.represent_scalar('tag:yaml.org,2002:str', data)

CustomDumper.add_representer(LiteralStr, _literal_str_representer)
CustomDumper.add_representer(LiteralStripStr, _literal_strip_str_representer)
CustomDumper.add_representer(str, _str_representer)
CustomDumper.add_representer(FlowList, _flow_list_repr)

GOLDEN_CASES = sorted(GOLDEN_ROOT.glob("*.yml"))


@pytest.mark.parametrize("golden_path", GOLDEN_CASES, ids=lambda path: path.stem)
def test_golden_cases(golden_path: Path) -> None:
    golden = yaml.safe_load(golden_path.read_text(encoding="utf-8"))

    source = golden["in_source"]
    in_input = golden.get("in_input", "")
    limit = golden.get("in_limit", 10000)

    tokenizer = Tokenizer()
    tokens = tokenizer.tokenize(source)
    program = Program()
    translate_program(tokens, program)
    machine_code = program.to_machine_code()

    binary_hex = "".join([f"{int(b, 2):08X}" for b in machine_code])
    code_log = build_hex_dump(program, machine_code) + "\n"

    schedule = parse_schedule(in_input) if in_input else []

    dp = DataPath(dmem_size=2048, imem_size=1024, input_schedule=schedule)
    dp.imem = [int(b, 2) for b in machine_code] + [0] * (1024 - len(machine_code))
    dp.dmem = program.data_memory + [0] * (2048 - len(program.data_memory))

    trace_io = io.StringIO()
    cu = ControlUnit(dp, trace_io)

    while not cu.halted and cu.tick_count < limit:
        cu.tick()

    trace_output = trace_io.getvalue()

    stdout_sym = ""
    for val in dp.out_buffer:
        stdout_sym += chr(val % 0x10FFFF)

    stdout_hex = [f"{val:02X}" for val in dp.out_buffer]
    stdout_dec = [f"{val}" for val in dp.out_buffer]

    if os.environ.get("UPDATE_GOLDENS") == '1':
        golden["in_source"] = LiteralStr(source)
        golden["in_input"] = LiteralStr(in_input)
        golden["out_stdout_hex"] = FlowList(stdout_hex)
        golden["out_stdout_dec"] = FlowList(stdout_dec)
        golden["out_stdout_sym"] = LiteralStr(stdout_sym)
        golden["out_code_log"] = LiteralStr(code_log)
        golden["out_binary_hex"] = binary_hex
        golden["out_trace"] = LiteralStr(trace_output)

        with open(golden_path, "w", encoding="utf-8") as f:
            yaml.dump(golden, f, Dumper=CustomDumper, allow_unicode=True, sort_keys=False, width=78, indent=2,)
        return

    assert trace_output == golden.get("out_trace", ""), f"Trace mismatch for {golden_path.stem}"
    assert binary_hex == golden.get("out_binary_hex", ""), f"Binary hex mismatch for {golden_path.stem}"
    assert code_log == golden.get("out_code_log", ""), f"Code log mismatch for {golden_path.stem}"
    assert stdout_sym == golden.get("out_stdout_sym", ""), f"Stdout sym mismatch for {golden_path.stem}"
    assert stdout_dec == golden.get("out_stdout_dec", ""), f"Stdout dec mismatch for {golden_path.stem}"
    assert stdout_hex == golden.get("out_stdout_hex", ""), f"Stdout hex mismatch for {golden_path.stem}"
