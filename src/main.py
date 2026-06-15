import argparse
import struct
import sys

from machine import run_simulation
from translator.tokenizer import Tokenizer
from translator.translator import Program, translate_program

def build_hex_dump(program: Program, machine_code: list[str]) -> str:
    """Формирует человеко-читаемый дамп скомпилированной программы."""
    lines = []
    lines.append("=== Instruction Memory (IMEM) ===")
    
    for i, (bin_str, instr) in enumerate(zip(machine_code, program.instructions)):
        # Преобразуем 32-битную строку из '0' и '1' в шестнадцатеричное число
        hex_val = f"0x{int(bin_str, 2):08X}"
        # Формат: index - команда(hex) - название команды
        lines.append(f"{i:04X} - {hex_val} - {instr}")
    
    if program.data_memory:
        lines.append("\n=== Data Memory (DMEM) ===")
        for i, val in enumerate(program.data_memory):
            # Маска 0xFFFFFFFF гарантирует корректный вывод отрицательных чисел
            hex_val = f"0x{val & 0xFFFFFFFF:08X}" 
            char_repr = repr(chr(val)) if 32 <= val <= 126 else "'.'"
            lines.append(f"{i:04X} - {hex_val} - {val} ({char_repr})")
            
    return "\n".join(lines)

def cmd_translate(args):
    """Логика трансляции в раздельные файлы (Harvard Architecture)."""
    source_name = args.source_name
    binary_name = args.imem_name
    memory_name = args.dmem_name
    debug_name = args.debug_name

    print(f"[*] Чтение исходного кода из {source_name}...")
    try:
        with open(source_name, 'r', encoding='utf-8') as f:
            source_code = f.read()
    except FileNotFoundError:
        print(f"[!] Ошибка: Файл {source_name} не найден.")
        sys.exit(1)

    print("[*] Токенизация и трансляция...")
    tokenizer = Tokenizer()
    tokens = tokenizer.tokenize(source_code)

    program = Program()
    translate_program(tokens, program)
    machine_code = program.to_machine_code()

    # 1. Запись памяти команд (IMEM)
    print(f"[*] Генерация бинарника инструкций: {binary_name}...")
    with open(binary_name, 'wb') as f:
        for bin_str in machine_code:
            f.write(struct.pack('>I', int(bin_str, 2)))

    # 2. Запись памяти данных (DMEM)
    print(f"[*] Генерация бинарника данных: {memory_name}...")
    with open(memory_name, 'wb') as f:
        for data_val in program.data_memory:
            f.write(struct.pack('>I', data_val & 0xFFFFFFFF))

    # 3. Запись файла дебага (если запрошен)
    if debug_name:
        print(f"[*] Генерация hex-дампа (debug): {debug_name}...")
        with open(debug_name, 'w', encoding='utf-8') as f:
            f.write(build_hex_dump(program, machine_code))

    print(f"[+] Трансляция успешно завершена!")
    print(f"    Инструкций (IMEM): {len(machine_code)} слов")
    print(f"    Данных (DMEM):     {len(program.data_memory)} слов")


def cmd_run(args):
    """Логика запуска симулятора."""
    schedule = []
    if args.input:
        try:
            with open(args.input, 'r') as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) == 2:
                        schedule.append((int(parts[0]), parts[1]))
        except FileNotFoundError:
            print(f"[-] Файл ввода {args.input} не найден.")
            
    # Передаем новый аргумент args.trace в функцию симуляции
    run_simulation(args.imem_name, args.dmem_name, schedule, trace_file=args.trace)


def main():
    parser = argparse.ArgumentParser(description="Транслятор и эмулятор Гарвардского RISC-процессора.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- Подкоманда: translate ---
    parser_translate = subparsers.add_parser('translate', help="Скомпилировать код")
    parser_translate.add_argument('source_name', help="Исходный текст программы")
    parser_translate.add_argument('imem_name', help="Выходной бинарный файл инструкций (IMEM)")
    parser_translate.add_argument('dmem_name', help="Выходной бинарный файл памяти (DMEM)")
    parser_translate.add_argument('debug_name', nargs='?', default=None, help="Файл для дебага (опционально)")
    parser_translate.set_defaults(func=cmd_translate)

    # --- Подкоманда: run ---
    parser_run = subparsers.add_parser('run', help="Запустить в эмуляторе")
    parser_run.add_argument('imem_name', help="Бинарный файл инструкций (IMEM)")
    parser_run.add_argument('dmem_name', help="Бинарный файл памяти (DMEM)")
    parser_run.add_argument('-i', '--input', help="Файл с токенами ввода", default=None)
    parser_run.add_argument('-t', '--trace', dest='trace', default=None, help="Путь к файлу трассировки логов (например, trace.log)")
    parser_run.set_defaults(func=cmd_run)

    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()