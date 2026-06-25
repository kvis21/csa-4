import sys
import struct
from src.isa import Opcode
from src.utils import ScheduleType
from typing import TextIO
from collections.abc import Generator

def sign_extend(value: int, bits: int) -> int:
    """Аппаратное расширение знака для отрицательных чисел."""
    sign_bit = 1 << (bits - 1)
    return (value & (sign_bit - 1)) - (value & sign_bit)


class DataPath:
    def __init__(self, dmem_size: int, imem_size: int, input_schedule: ScheduleType):
        self.dmem = [0] * dmem_size
        self.imem = [0] * imem_size

        self.regs = [0] * 8

        self.regs[6] = dmem_size - 1
        self.regs[7] = dmem_size // 2

        self.pc = 0

        self.ir = 0
        self.ar = 0
        self.data_bus = 0

        self.sr_n = 0
        self.sr_z = 0
        self.sr_ie = 0

        self.input_schedule = input_schedule
        self.in_buffer: list[int] = []
        self.out_buffer: list[int] = []

    def get_sr(self) -> int:
        """Аппаратная упаковка флагов в машинное слово для IRET/TRAP."""
        return (self.sr_n << 2) | (self.sr_z << 1) | self.sr_ie

    def set_sr(self, val: int) -> None:
        self.sr_n = (val >> 2) & 1
        self.sr_z = (val >> 1) & 1
        self.sr_ie = val & 1

    def alu_execute(self, op: Opcode, a: int, b: int) -> int:
        res = 0
        if op == Opcode.ADD:
            res = a + b
        elif op == Opcode.SUB or op == Opcode.CMP:
            res = a - b
        elif op == Opcode.MUL:
            res = a * b
        elif op == Opcode.DIV:
            res = a // b if b != 0 else 0
        elif op == Opcode.MOD:
            res = a % b if b != 0 else 0

        res = sign_extend(res & 0xFFFFFFFF, 32)

        self.sr_n = 1 if res < 0 else 0
        self.sr_z = 1 if res == 0 else 0

        return res

    def check_interrupt_req(self, current_tick: int) -> bool:
        """IO Controller: проверка линии прерывания."""
        while self.input_schedule and self.input_schedule[0][0] <= current_tick:
            _, char = self.input_schedule.pop(0)
            self.in_buffer.append(char)
        return len(self.in_buffer) > 0


class ControlUnit:
    def __init__(self, dp: DataPath, output: TextIO = sys.stdout):
        self.dp = dp
        self.tick_count = 0
        self.halted = False
        self._fsm = self._microcode_fsm()
        self.output = output

    def tick(self) -> None:
        """Продвигает процессор на 1 такт."""
        if self.halted:
            return

        self.tick_count += 1

        self.dp.check_interrupt_req(self.tick_count)

        try:
            phase = next(self._fsm)
            self._log_state(phase)
        except StopIteration:
            self.halted = True

    def _microcode_fsm(self) -> Generator[str]:
        """
        Генератор, моделирующий логику Step Counter и Control HW Matrix.
        """
        while True:
            # 1. INTERRUPT LOGIC
            if self.dp.sr_ie and len(self.dp.in_buffer) > 0:
                yield "INT1"
                self.dp.regs[7] -= 1
                self.dp.ar = self.dp.regs[7]
                self.dp.dmem[self.dp.ar] = self.dp.pc

                yield "INT2"
                self.dp.regs[7] -= 1
                self.dp.ar = self.dp.regs[7]
                self.dp.dmem[self.dp.ar] = self.dp.get_sr()

                yield "INT3"
                self.dp.sr_ie = 0
                self.dp.pc = self.dp.imem[1]
                continue

            # 2. INSTRUCTION FETCH (IF)
            self.dp.ir = self.dp.imem[self.dp.pc]
            if self.dp.ir == 0:
                self.halted = True
                yield "HALT"
                break

            self.dp.pc += 1
            yield "IF"

            # 3. ADDRESS FETCH (AF)
            opcode_val = (self.dp.ir >> 25) & 0x7F
            try:
                opcode = Opcode(opcode_val)
            except ValueError:
                self.halted = True
                yield "ERR"
                break

            rd, rs1, am = 0, 0, 0
            if opcode in (Opcode.LD, Opcode.ST):
                rd = (self.dp.ir >> 22) & 0x7
                am = (self.dp.ir >> 21) & 0x1
            elif opcode == Opcode.LUI:
                rd = (self.dp.ir >> 22) & 0x7
            elif opcode in (Opcode.ADD, Opcode.SUB, Opcode.MUL, Opcode.DIV, Opcode.MOD, Opcode.CMP):
                rd = (self.dp.ir >> 22) & 0x7
                rs1 = (self.dp.ir >> 19) & 0x7
                am = (self.dp.ir >> 18) & 0x1
            elif opcode in (Opcode.IN, Opcode.OUT) or opcode in (Opcode.PUSH, Opcode.POP):
                rd = (self.dp.ir >> 22) & 0x7

            yield "AF"
            # 4. EXECUTE PHASE (EF) - Длительность зависит от инструкции
            if opcode == Opcode.LUI:
                imm22 = self.dp.ir & 0x3FFFFF
                self.dp.regs[rd] = sign_extend(imm22, 22) << 10
                yield "EX1"

            elif opcode in (Opcode.LD, Opcode.ST):
                if am == 0:
                    self.dp.ar = self.dp.ir & 0x1FFFFF
                else:
                    rs_mem = (self.dp.ir >> 18) & 0x7
                    self.dp.ar = self.dp.regs[rs_mem]

                if opcode == Opcode.LD:
                    self.dp.data_bus = self.dp.dmem[self.dp.ar]
                    yield "EX1"
                    self.dp.regs[rd] = self.dp.data_bus
                    yield "EX2"
                else:
                    self.dp.dmem[self.dp.ar] = self.dp.regs[rd]
                    yield "EX1"
                    yield "EX2"

            elif opcode in (Opcode.ADD, Opcode.SUB, Opcode.MUL, Opcode.DIV, Opcode.MOD, Opcode.CMP):
                rs1_val = self.dp.regs[rs1]
                if am == 1:
                    operand2 = sign_extend(self.dp.ir & 0x3FFFF, 18)
                else:
                    rs2 = (self.dp.ir >> 15) & 0x7
                    operand2 = self.dp.regs[rs2]

                res = self.dp.alu_execute(opcode, rs1_val, operand2)
                if opcode != Opcode.CMP:
                    self.dp.regs[rd] = res
                yield "EX1"

            elif opcode in (Opcode.JMP, Opcode.BEQ, Opcode.BNE, Opcode.BGT, Opcode.BLT):
                addr25 = self.dp.ir & 0x1FFFFFF
                take_branch = False
                if (
                    opcode == Opcode.JMP
                    or opcode == Opcode.BEQ
                    and self.dp.sr_z == 1
                    or opcode == Opcode.BNE
                    and self.dp.sr_z == 0
                    or opcode == Opcode.BGT
                    and self.dp.sr_z == 0
                    and self.dp.sr_n == 0
                    or opcode == Opcode.BLT
                    and self.dp.sr_n == 1
                ):
                    take_branch = True

                if take_branch:
                    self.dp.pc = addr25
                yield "EX1"

            elif opcode == Opcode.CALL:
                addr25 = self.dp.ir & 0x1FFFFFF
                self.dp.regs[7] -= 1
                self.dp.ar = self.dp.regs[7]
                yield "EX1"
                self.dp.dmem[self.dp.ar] = self.dp.pc
                self.dp.pc = addr25
                yield "EX2"

            elif opcode == Opcode.RET:
                self.dp.ar = self.dp.regs[7]
                yield "EX1"
                self.dp.pc = self.dp.dmem[self.dp.ar]
                self.dp.regs[7] += 1
                yield "EX2"

            elif opcode == Opcode.PUSH:
                self.dp.regs[6] -= 1
                self.dp.ar = self.dp.regs[6]
                yield "EX1"
                self.dp.dmem[self.dp.ar] = self.dp.regs[rd]
                yield "EX2"

            elif opcode == Opcode.POP:
                self.dp.ar = self.dp.regs[6]
                yield "EX1"
                self.dp.regs[rd] = self.dp.dmem[self.dp.ar]
                self.dp.regs[6] += 1
                yield "EX2"

            elif opcode == Opcode.IN:
                port = self.dp.ir & 0x3FFFFF
                if port == 0:
                    if self.dp.in_buffer:
                        self.dp.regs[rd] = self.dp.in_buffer.pop(0)
                    else:
                        self.dp.regs[rd] = 0
                yield "EX1"

            elif opcode == Opcode.OUT:
                port = self.dp.ir & 0x3FFFFF
                if port == 1:
                    val = self.dp.regs[rd]
                    self.dp.out_buffer.append(val)
                yield "EX1"

            elif opcode == Opcode.EI:
                self.dp.sr_ie = 1
                yield "EX1"

            elif opcode == Opcode.DI:
                self.dp.sr_ie = 0
                yield "EX1"

            elif opcode == Opcode.HLT:
                self.halted = True
                yield "HALT"
                return

            elif opcode == Opcode.IRET:
                self.dp.ar = self.dp.regs[7]
                yield "EX1"
                self.dp.set_sr(self.dp.dmem[self.dp.ar])
                self.dp.regs[7] += 1
                yield "EX2"

                self.dp.ar = self.dp.regs[7]
                yield "EX3"
                self.dp.pc = self.dp.dmem[self.dp.ar]
                self.dp.regs[7] += 1
                yield "EX4"

    def _log_state(self, phase: str) -> None:
        flags = f"N:{self.dp.sr_n} Z:{self.dp.sr_z} IE:{self.dp.sr_ie}"
        r_str = "  ".join([f"R{i}:{self.dp.regs[i]:04X}" for i in range(8)])
        log_str = (
            f"Tick: {self.tick_count:04} | {phase:^4} |  "
            f"PC: {self.dp.pc:04X} | IR: {self.dp.ir:08X} |  "
            f"AR: {self.dp.ar:04X} | {flags} | {r_str}"
        )
        print(log_str, file=self.output)


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
                   trace_file: str = "") -> None:
    """Точка входа для запуска эмулятора."""
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
