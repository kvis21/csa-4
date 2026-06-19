import pytest
import io
import os, sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from translator.tokenizer import Tokenizer
from translator.translator import Program, translate_program
from utils import build_hex_dump, parse_schedule
from machine import DataPath, ControlUnit


@pytest.mark.golden_test("golden/*.yml")
def test_processor(golden):
    source = golden["in_source"]

    tokenizer = Tokenizer()
    tokens = tokenizer.tokenize(source)
    program = Program()
    translate_program(tokens, program)
    machine_code = program.to_machine_code()

    binary_hex = "".join([f"{int(b, 2):08X}" for b in machine_code]) 
    code_log = build_hex_dump(program, machine_code) + "\n"

    in_input = golden.get("in_input")

    schedule = parse_schedule(in_input) if in_input else []

    limit = golden.get("in_limit", 10000)

    dp = DataPath(dmem_size=2048, imem_size=1024, input_schedule=schedule)

    dp.imem = [int(b, 2) for b in machine_code] + [0] * (1024 - len(machine_code))
    dp.dmem = program.data_memory + [0] * (2048 - len(program.data_memory))

    trace_io = io.StringIO()
    cu = ControlUnit(dp, trace_io)

    print("=== ЗАПУСК СИМУЛЯЦИИ ===", file=trace_io)
    while not cu.halted and cu.tick_count < limit:
        cu.tick()

    # 6. Сбор результатов выполнения
    trace_output = trace_io.getvalue()
    stdout_output = "".join(dp.out_buffer)

    # 7. Сравнение с ожидаемыми результатами
    assert trace_output == golden.out["out_trace"]
    assert binary_hex == golden.out["out_binary_hex"]
    assert code_log == golden.out["out_code_log"]
    assert stdout_output == golden.out["out_stdout"]
