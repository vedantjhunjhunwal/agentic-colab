"""
============================================================
  DSL Compiler – Phase 4: TARGET CODE GENERATOR
  Translates TAC into a simple stack-based assembly language
  Target: Simplified x86-like assembly (educational)
============================================================
"""

from typing import List, Dict, Set
from icg    import TACInstr


# ──────────────────────────────────────────────────────────
#  Assembly instruction
# ──────────────────────────────────────────────────────────
class AsmLine:
    def __init__(self, text: str, comment: str = ""):
        self.text    = text
        self.comment = comment

    def __str__(self):
        if self.comment:
            pad = max(0, 40 - len(self.text))
            return f"{self.text}{' ' * pad}; {self.comment}"
        return self.text


# ──────────────────────────────────────────────────────────
#  Code Generator
# ──────────────────────────────────────────────────────────
class CodeGen:
    """
    Generates simple register-based assembly from TAC.
    Registers: AX, BX, CX, DX  (general purpose)
    Stack-based calling convention.
    """
    REGISTERS = ['AX', 'BX', 'CX', 'DX', 'EX', 'FX']

    def __init__(self, tac: List[TACInstr]):
        self.tac:       List[TACInstr] = tac
        self.asm:       List[AsmLine]  = []
        self._reg_map:  Dict[str, str] = {}   # var/temp → register or memory
        self._mem_vars: Set[str]       = set()
        self._data_seg: List[str]      = []   # data segment declarations
        self._str_count = 0

    def generate(self) -> List[AsmLine]:
        self._emit_header()
        self._collect_variables()
        self._emit_data_segment()
        self._emit_code_segment()
        return self.asm

    # ── Header ────────────────────────────────────────────
    def _emit_header(self):
        self.asm.append(AsmLine("; ================================================"))
        self.asm.append(AsmLine("; Generated Assembly Code"))
        self.asm.append(AsmLine("; DSL Compiler – Code Generator Phase"))
        self.asm.append(AsmLine("; Target: Simplified Educational x86-like Assembly"))
        self.asm.append(AsmLine("; ================================================"))
        self.asm.append(AsmLine(""))

    def _a(self, text: str, comment: str = ""):
        self.asm.append(AsmLine(text, comment))

    # ── Collect all variables / temps for data segment ────
    def _collect_variables(self):
        declared = set()
        for instr in self.tac:
            for field in (instr.result, instr.arg1, instr.arg2):
                if field is None:
                    continue
                if field.startswith(('t', 'T')) and field[1:].isdigit():
                    declared.add(field)
                elif (field.isidentifier() and
                      not field.isupper() and
                      not field.startswith('"') and
                      not field.startswith("'") and
                      not field.lstrip('-').isdigit()):
                    declared.add(field)
        self._mem_vars = declared

    def _emit_data_segment(self):
        self._a(".DATA")
        for var in sorted(self._mem_vars):
            self._a(f"    {var:<16} DW  0", f"variable/temp {var}")
        self._a("")

    def _emit_code_segment(self):
        self._a(".CODE")
        self._a("")
        for instr in self.tac:
            self._translate(instr)
        self._a("")
        self._a("END")

    # ── Translate one TAC instruction ─────────────────────
    def _translate(self, instr: TACInstr):
        op = instr.op

        # ── Label ─────────────────────────────────────────
        if op == 'LABEL':
            self._a(f"{instr.result}:", "")
            return

        # ── HALT ──────────────────────────────────────────
        if op == 'HALT':
            self._a("    MOV AX, 4C00h",  "DOS exit")
            self._a("    INT 21h")
            return

        # ── COPY  result = arg1 ───────────────────────────
        if op == 'COPY':
            src = self._load_to_reg(instr.arg1, 'AX')
            self._a(f"    MOV [{instr.result}], {src}", f"{instr.result} = {instr.arg1}")
            return

        # ── Arithmetic ────────────────────────────────────
        if op in ('+', '-', '*', '/'):
            a = self._load_to_reg(instr.arg1, 'AX')
            b = self._load_to_reg(instr.arg2, 'BX')
            if op == '+':
                self._a(f"    ADD {a}, {b}", f"{instr.result} = {instr.arg1} + {instr.arg2}")
            elif op == '-':
                self._a(f"    SUB {a}, {b}", f"{instr.result} = {instr.arg1} - {instr.arg2}")
            elif op == '*':
                self._a(f"    IMUL {a}, {b}", f"{instr.result} = {instr.arg1} * {instr.arg2}")
            elif op == '/':
                self._a("    XOR DX, DX",  "clear DX for division")
                self._a(f"    IDIV {b}", f"{instr.result} = {instr.arg1} / {instr.arg2}")
                a = 'AX'   # quotient in AX
            self._a(f"    MOV [{instr.result}], {a}", f"store result")
            return

        # ── Unary ─────────────────────────────────────────
        if op == 'NEG':
            a = self._load_to_reg(instr.arg1, 'AX')
            self._a(f"    NEG {a}", f"{instr.result} = -{instr.arg1}")
            self._a(f"    MOV [{instr.result}], {a}")
            return

        if op == 'NOT':
            a = self._load_to_reg(instr.arg1, 'AX')
            self._a(f"    NOT {a}", f"{instr.result} = NOT {instr.arg1}")
            self._a(f"    MOV [{instr.result}], {a}")
            return

        # ── Logical ───────────────────────────────────────
        if op in ('AND', 'OR'):
            a = self._load_to_reg(instr.arg1, 'AX')
            b = self._load_to_reg(instr.arg2, 'BX')
            self._a(f"    {op} {a}, {b}", f"{instr.result} = {instr.arg1} {op} {instr.arg2}")
            self._a(f"    MOV [{instr.result}], {a}")
            return

        # ── Relational ────────────────────────────────────
        if op in ('<', '>', '<=', '>=', '==', '!='):
            a = self._load_to_reg(instr.arg1, 'AX')
            b = self._load_to_reg(instr.arg2, 'BX')
            lbl_true  = f"CMP_T_{instr.result}"
            lbl_end   = f"CMP_E_{instr.result}"
            self._a(f"    CMP {a}, {b}", f"compare {instr.arg1} {op} {instr.arg2}")
            jmp_map = {'<': 'JL', '>': 'JG', '<=': 'JLE',
                       '>=': 'JGE', '==': 'JE', '!=': 'JNE'}
            self._a(f"    {jmp_map[op]} {lbl_true}")
            self._a(f"    MOV [{instr.result}], 0")
            self._a(f"    JMP {lbl_end}")
            self._a(f"{lbl_true}:")
            self._a(f"    MOV [{instr.result}], 1")
            self._a(f"{lbl_end}:")
            return

        # ── Control flow ──────────────────────────────────
        if op == 'GOTO':
            self._a(f"    JMP {instr.result}", "unconditional jump")
            return

        if op == 'IF_FALSE':
            cond = self._load_to_reg(instr.arg1, 'AX')
            self._a(f"    CMP {cond}, 0", f"if {instr.arg1} is false")
            self._a(f"    JE  {instr.result}", f"jump to {instr.result}")
            return

        if op == 'IF_TRUE':
            cond = self._load_to_reg(instr.arg1, 'AX')
            self._a(f"    CMP {cond}, 0")
            self._a(f"    JNE {instr.result}")
            return

        # ── Array ─────────────────────────────────────────
        if op == 'ARRAY_LOAD':
            self._a(f"    MOV BX, [{instr.arg2}]",  f"load index {instr.arg2}")
            self._a(f"    SHL BX, 1",                "multiply by 2 (word size)")
            self._a(f"    MOV AX, [{instr.arg1}+BX]", f"load {instr.arg1}[{instr.arg2}]")
            self._a(f"    MOV [{instr.result}], AX",   f"store to {instr.result}")
            return

        if op == 'ARRAY_STORE':
            self._a(f"    MOV BX, [{instr.arg1}]",   f"load index {instr.arg1}")
            self._a(f"    SHL BX, 1",                 "multiply by 2 (word size)")
            val = self._load_to_reg(instr.arg2, 'AX')
            self._a(f"    MOV [{instr.result}+BX], {val}", f"{instr.result}[{instr.arg1}] = {instr.arg2}")
            return

        # ── I/O ───────────────────────────────────────────
        if op == 'READ':
            self._a(f"    ; --- READ {instr.arg1} ---")
            self._a(f"    MOV AH, 01h",  "DOS read character")
            self._a(f"    INT 21h")
            self._a(f"    SUB AL, '0'",  "ASCII to integer")
            self._a(f"    MOV AH, 0")
            self._a(f"    MOV [{instr.arg1}], AX", f"store to {instr.arg1}")
            return

        if op == 'WRITE':
            self._a(f"    ; --- WRITE {instr.arg1} ---")
            val = self._load_to_reg(instr.arg1, 'AX')
            self._a(f"    ADD AL, '0'",  "integer to ASCII (simple)")
            self._a(f"    MOV DL, AL")
            self._a(f"    MOV AH, 02h",  "DOS print character")
            self._a(f"    INT 21h")
            return

        if op == 'WRITE_STR':
            s_lbl = f"STR_{self._str_count}"
            self._str_count += 1
            raw = instr.arg1.strip("'\"")
            self._a(f"    ; --- WRITE_STR {raw[:30]} ---")
            self._a(f"    LEA DX, [{s_lbl}]")
            self._a(f"    MOV AH, 09h",  "DOS print string")
            self._a(f"    INT 21h")
            self._data_seg.append(f"    {s_lbl:<16} DB '{raw}', '$'")
            return

        # ── Procedure call ────────────────────────────────
        if op == 'PARAM':
            val = self._load_to_reg(instr.arg1, 'AX')
            self._a(f"    PUSH {val}", f"push param {instr.arg1}")
            return

        if op == 'CALL':
            self._a(f"    CALL {instr.arg1}", f"call {instr.arg1} with {instr.arg2} args")
            if instr.result:
                self._a(f"    MOV [{instr.result}], AX", "save return value")
            return

        if op == 'RETURN':
            if instr.arg1:
                val = self._load_to_reg(instr.arg1, 'AX')
            self._a("    RET", "return from subprogram")
            return

        # ── Fallback ──────────────────────────────────────
        self._a(f"    ; [UNHANDLED] {instr}")

    def _load_to_reg(self, operand: str, reg: str) -> str:
        """Emit a MOV instruction to load operand into reg. Returns reg name."""
        if operand is None:
            return reg
        if operand.lstrip('-').isdigit():
            self._a(f"    MOV {reg}, {operand}")
        elif operand.startswith('"') or operand.startswith("'"):
            pass  # string literal, handled elsewhere
        else:
            self._a(f"    MOV {reg}, [{operand}]")
        return reg

    # ── Pretty print ──────────────────────────────────────
    def print_asm(self):
        print("\n" + "═" * 60)
        print("  GENERATED ASSEMBLY CODE")
        print("═" * 60)
        for line in self.asm:
            print(f"  {line}")
        print("═" * 60)

    def get_asm_string(self) -> str:
        return '\n'.join(str(line) for line in self.asm)
