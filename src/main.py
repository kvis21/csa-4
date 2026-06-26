import argparse
from argparse import Namespace
import struct
import sys

from src.utils import run_simulation
from src.translator.tokenizer import Tokenizer
from src.translator.translator import Program, translate_program
from src.utils import build_hex_dump, parse_schedule


def cmd_translate(args: Namespace) -> None:
    source_name = args.source_name
    binary_name = args.imem_name
    memory_name = args.dmem_name
    debug_name = args.debug_name

    print(f"Чтение исходного кода из {source_name}")
    try:
        with open(source_name, encoding="utf-8") as f:
            source_code = f.read()
    except FileNotFoundError:
        print(f"Ошибка: Файл {source_name} не найден.")
        sys.exit(1)

    tokenizer = Tokenizer()
    tokens = tokenizer.tokenize(source_code)

    program = Program()
    translate_program(tokens, program)
    machine_code = program.to_machine_code()

    print(f"Генерация бинарника инструкций: {binary_name}")
    with open(binary_name, "wb") as f:
        for bin_str in machine_code:
            f.write(struct.pack(">I", int(bin_str, 2)))

    print(f"Генерация бинарника данных: {memory_name}")
    with open(memory_name, "wb") as f:
        for data_val in program.data_memory:
            f.write(struct.pack(">I", data_val & 0xFFFFFFFF))

    if debug_name:
        print(f"Генерация hex-дампа (debug): {debug_name}")
        with open(debug_name, "w", encoding="utf-8") as f:
            f.write(build_hex_dump(program, machine_code))
    print(f"    Инструкций (IMEM): {len(machine_code)} слов")
    print(f"    Данных (DMEM):     {len(program.data_memory)} слов")
    print(build_hex_dump(program, machine_code))

def cmd_run(args: Namespace) -> None:
    schedule = []
    if args.input:
        try:
            with open(args.input, encoding="utf-8") as f:
                schedule = parse_schedule(f.read())
        except FileNotFoundError:
            print(f"Ошибка: Файл {args.input} не найден.")
    out = run_simulation(args.imem_name, args.dmem_name, schedule, trace_file=args.trace)

    stdout_sym = ""
    for val in out:
        stdout_sym += chr(val % 0x10FFFF)
    print(stdout_sym)

def main() -> None:
    parser = argparse.ArgumentParser(description="Транслятор и эмулятор Гарвардского RISC-процессора.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    parser_translate = subparsers.add_parser("translate", help="Скомпилировать код")
    parser_translate.add_argument("source_name", help="Исходный текст программы")
    parser_translate.add_argument("imem_name", help="Выходной бинарный файл инструкций (IMEM)")
    parser_translate.add_argument("dmem_name", help="Выходной бинарный файл памяти (DMEM)")
    parser_translate.add_argument("debug_name", nargs="?", default=None, help="Файл для дебага (опционально)")
    parser_translate.set_defaults(func=cmd_translate)

    parser_run = subparsers.add_parser("run", help="Запустить в эмуляторе")
    parser_run.add_argument("imem_name", help="Бинарный файл инструкций (IMEM)")
    parser_run.add_argument("dmem_name", help="Бинарный файл памяти (DMEM)")
    parser_run.add_argument("-i", "--input", help="Файл с токенами ввода", default=None)
    parser_run.add_argument(
        "-t", "--trace", dest="trace", default=None, help="Путь к файлу трассировки логов (например, trace.log)"
    )
    parser_run.set_defaults(func=cmd_run)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
