"""
============================================================
  DSL Compiler – Phase 3: INTERMEDIATE CODE GENERATOR
  Generates Three-Address Code (TAC) from the AST
  Also performs semantic checking (type checking, undeclared vars)
============================================================
"""

from dataclasses import dataclass, field
from typing      import List, Optional, Dict
from ast_nodes   import *
from symbol_table import SymbolTable, IntegerType, ArrayType, FunctionType, ProcedureType


# ──────────────────────────────────────────────────────────
#  TAC instruction types
# ──────────────────────────────────────────────────────────
@dataclass
class TACInstr:
    op:     str
    result: Optional[str] = None
    arg1:   Optional[str] = None
    arg2:   Optional[str] = None

    def __str__(self):
        if self.op == 'LABEL':
            return f"{self.result}:"
        if self.op == 'GOTO':
            return f"    GOTO    {self.result}"
        if self.op == 'IF_FALSE':
            return f"    IF_FALSE {self.arg1}  GOTO  {self.result}"
        if self.op == 'IF_TRUE':
            return f"    IF_TRUE  {self.arg1}  GOTO  {self.result}"
        if self.op == 'PARAM':
            return f"    PARAM   {self.arg1}"
        if self.op == 'CALL':
            return f"    CALL    {self.arg1}, {self.arg2}"
        if self.op in ('READ', 'WRITE', 'WRITE_STR'):
            return f"    {self.op:<10} {self.arg1}"
        if self.op == 'RETURN':
            return f"    RETURN  {self.arg1 or ''}"
        if self.op == 'HALT':
            return f"    HALT"
        if self.arg2:
            return f"    {self.result:<12} = {self.arg1}  {self.op}  {self.arg2}"
        if self.arg1:
            if self.op == 'COPY':
                return f"    {self.result:<12} = {self.arg1}"
            if self.op == 'NEG':
                return f"    {self.result:<12} = - {self.arg1}"
            if self.op == 'NOT':
                return f"    {self.result:<12} = NOT {self.arg1}"
            if self.op == 'ARRAY_LOAD':
                return f"    {self.result:<12} = {self.arg1}[{self.arg2}]"
            if self.op == 'ARRAY_STORE':
                return f"    {self.result}[{self.arg1}] = {self.arg2}"
        return f"    {self.op} {self.result} {self.arg1} {self.arg2}"


# ──────────────────────────────────────────────────────────
#  ICG class
# ──────────────────────────────────────────────────────────
class ICG:
    def __init__(self):
        self.code:    List[TACInstr] = []
        self.errors:  List[str]      = []
        self.sym_tab: SymbolTable    = SymbolTable()
        self._temp_count  = 0
        self._label_count = 0

    # ── Helpers ───────────────────────────────────────────
    def _new_temp(self) -> str:
        t = f"t{self._temp_count}"
        self._temp_count += 1
        return t

    def _new_label(self) -> str:
        lbl = f"L{self._label_count}"
        self._label_count += 1
        return lbl

    def _emit(self, op, result=None, arg1=None, arg2=None):
        self.code.append(TACInstr(op=op, result=result, arg1=arg1, arg2=arg2))

    def _sem_error(self, msg: str, node: ASTNode):
        self.errors.append(f"[SEM ERROR] Line {node.line}: {msg}")

    # ── Entry ─────────────────────────────────────────────
    def generate(self, ast: ProgramNode) -> List[TACInstr]:
        self._gen_program(ast)
        return self.code

    # ── Program ───────────────────────────────────────────
    def _gen_program(self, node: ProgramNode):
        self._emit('LABEL', result=f"PROG_{node.name.upper()}")
        # Declare variables in global scope
        for decl in node.var_decls:
            self._declare_vars(decl)
        # Subprograms
        for sub in node.subprograms:
            self._gen_subprogram(sub)
        # Main body
        self._emit('LABEL', result='MAIN')
        self._gen_compound(node.body)
        self._emit('HALT')

    def _declare_vars(self, decl: VarDeclNode):
        type_obj = self._make_type(decl.var_type)
        for name in decl.names:
            ok = self.sym_tab.declare(name, type_obj, decl.line)
            if not ok:
                self._sem_error(f"Duplicate declaration of '{name}'", decl)

    def _make_type(self, type_node: Optional[TypeNode]):
        if type_node is None:
            return IntegerType()
        if type_node.type_name == 'integer':
            return IntegerType()
        if type_node.type_name.startswith('array'):
            return ArrayType(low=type_node.low or 0, high=type_node.high or 0)
        return IntegerType()

    # ── Subprogram ────────────────────────────────────────
    def _gen_subprogram(self, node: SubprogramNode):
        lbl = node.name.upper()
        self._emit('LABEL', result=lbl)
        self.sym_tab.enter_scope(node.name)
        # For functions: declare the function name as a local var (Pascal return convention)
        if node.kind == 'function':
            return_type = IntegerType()
            self.sym_tab.declare(node.name, return_type, node.line)

        # Declare params
        param_idx = 0
        for param_decl in node.params:
            type_obj = self._make_type(param_decl.var_type)
            for name in param_decl.names:
                self.sym_tab.declare(name, type_obj, node.line,
                                     is_param=True, param_index=param_idx)
                param_idx += 1
        # Declare local vars
        for decl in node.var_decls:
            self._declare_vars(decl)
        # Body
        self._gen_compound(node.body)
        self._emit('RETURN')
        self.sym_tab.exit_scope()

    # ── Compound ─────────────────────────────────────────
    def _gen_compound(self, node: Optional[CompoundStmt]):
        if node is None:
            return
        for stmt in node.statements:
            if stmt is not None:
                self._gen_stmt(stmt)

    # ── Statement dispatch ────────────────────────────────
    def _gen_stmt(self, node: ASTNode):
        if isinstance(node, AssignStmt):
            self._gen_assign(node)
        elif isinstance(node, IfStmt):
            self._gen_if(node)
        elif isinstance(node, WhileStmt):
            self._gen_while(node)
        elif isinstance(node, ReadStmt):
            self._gen_read(node)
        elif isinstance(node, WriteStmt):
            self._gen_write(node)
        elif isinstance(node, ProcCallStmt):
            self._gen_proc_call(node)
        elif isinstance(node, CompoundStmt):
            self._gen_compound(node)

    # ── Assignment ────────────────────────────────────────
    def _gen_assign(self, node: AssignStmt):
        val = self._gen_expr(node.value)
        var = node.variable
        sym = self.sym_tab.lookup(var.name)
        if sym is None:
            self._sem_error(f"Undeclared variable '{var.name}'", node)
        if var.index is not None:
            idx = self._gen_expr(var.index)
            self._emit('ARRAY_STORE', result=var.name, arg1=idx, arg2=val)
        else:
            self._emit('COPY', result=var.name, arg1=val)

    # ── If ────────────────────────────────────────────────
    def _gen_if(self, node: IfStmt):
        cond  = self._gen_expr(node.condition)
        lbl_else = self._new_label()
        lbl_end  = self._new_label()
        self._emit('IF_FALSE', result=lbl_else, arg1=cond)
        self._gen_stmt(node.then_stmt)
        if node.else_stmt:
            self._emit('GOTO', result=lbl_end)
            self._emit('LABEL', result=lbl_else)
            self._gen_stmt(node.else_stmt)
            self._emit('LABEL', result=lbl_end)
        else:
            self._emit('LABEL', result=lbl_else)

    # ── While ─────────────────────────────────────────────
    def _gen_while(self, node: WhileStmt):
        lbl_start = self._new_label()
        lbl_end   = self._new_label()
        self._emit('LABEL', result=lbl_start)
        cond = self._gen_expr(node.condition)
        self._emit('IF_FALSE', result=lbl_end, arg1=cond)
        self._gen_stmt(node.body)
        self._emit('GOTO', result=lbl_start)
        self._emit('LABEL', result=lbl_end)

    # ── Read / Write ──────────────────────────────────────
    def _gen_read(self, node: ReadStmt):
        for var in node.variables:
            sym = self.sym_tab.lookup(var.name)
            if sym is None:
                self._sem_error(f"Undeclared variable '{var.name}'", node)
            self._emit('READ', arg1=var.name)

    def _gen_write(self, node: WriteStmt):
        for item in node.items:
            if isinstance(item, StringLiteral):
                self._emit('WRITE_STR', arg1=repr(item.value))
            else:
                val = self._gen_expr(item)
                self._emit('WRITE', arg1=val)

    # ── Procedure call ────────────────────────────────────
    def _gen_proc_call(self, node: ProcCallStmt):
        for arg in node.arguments:
            val = self._gen_expr(arg)
            self._emit('PARAM', arg1=val)
        self._emit('CALL', arg1=node.name.upper(), arg2=str(len(node.arguments)))

    # ── Expression → returns temp/name/literal ────────────
    def _gen_expr(self, node: ASTNode) -> str:
        if isinstance(node, IntegerLiteral):
            return str(node.value)

        if isinstance(node, StringLiteral):
            return repr(node.value)

        if isinstance(node, VariableExpr):
            sym = self.sym_tab.lookup(node.name)
            if sym is None:
                self._sem_error(f"Undeclared variable '{node.name}'", node)
            if node.index is not None:
                idx = self._gen_expr(node.index)
                t   = self._new_temp()
                self._emit('ARRAY_LOAD', result=t, arg1=node.name, arg2=idx)
                return t
            return node.name

        if isinstance(node, UnaryExpr):
            op_map = {'-': 'NEG', 'not': 'NOT'}
            op_tac = op_map.get(node.op, node.op.upper())
            operand = self._gen_expr(node.operand)
            t = self._new_temp()
            self._emit(op_tac, result=t, arg1=operand)
            return t

        if isinstance(node, BinaryExpr):
            left  = self._gen_expr(node.left)
            right = self._gen_expr(node.right)
            t     = self._new_temp()
            op_map = {
                '+': '+', '-': '-', '*': '*', '/': '/',
                'or': 'OR', 'and': 'AND',
                '<': '<', '>': '>', '<=': '<=', '>=': '>=',
                '=': '==', '<>': '!='
            }
            tac_op = op_map.get(node.op, node.op)
            self._emit(tac_op, result=t, arg1=left, arg2=right)
            return t

        if isinstance(node, FuncCallExpr):
            for arg in node.arguments:
                val = self._gen_expr(arg)
                self._emit('PARAM', arg1=val)
            t = self._new_temp()
            self._emit('CALL', result=t, arg1=node.name.upper(), arg2=str(len(node.arguments)))
            return t

        return '0'  # fallback

    # ── Print TAC ─────────────────────────────────────────
    def print_tac(self):
        print("\n" + "═" * 60)
        print("  THREE-ADDRESS CODE (TAC)")
        print("═" * 60)
        for i, instr in enumerate(self.code):
            print(f"  {i:3d}  {instr}")
        print("═" * 60)
