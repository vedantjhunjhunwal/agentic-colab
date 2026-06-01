from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ast_nodes import (
    ProgramNode, VarDeclNode, TypeNode, SubprogramNode, CompoundStmt, AssignStmt,
    IfStmt, WhileStmt, ReadStmt, WriteStmt, ProcCallStmt, BinaryExpr, UnaryExpr,
    VariableExpr, IntegerLiteral, StringLiteral, FuncCallExpr, ASTNode,
)


class RuntimeExecutionError(Exception):
    def __init__(self, message: str, line: int | None = None, col: int | None = None):
        super().__init__(message)
        self.message = message
        self.line = line
        self.col = col

    def __str__(self):
        return self.message


@dataclass
class Cell:
    value: Any = 0


class Frame:
    def __init__(self, parent: Optional['Frame'] = None):
        self.parent = parent
        self.vars: Dict[str, Cell] = {}

    def declare(self, name: str, value: Any = 0):
        self.vars[name.lower()] = Cell(value)

    def resolve_cell(self, name: str) -> Cell:
        key = name.lower()
        cur: Optional[Frame] = self
        while cur is not None:
            if key in cur.vars:
                return cur.vars[key]
            cur = cur.parent
        raise RuntimeExecutionError(f"Undeclared identifier '{name}'")


class Interpreter:
    def __init__(self, inputs: Optional[List[int]] = None):
        self.inputs = list(inputs or [])
        self.input_index = 0
        self.output_buffer: List[str] = []
        self.runtime_warnings: List[str] = []
        self.subprograms: Dict[str, SubprogramNode] = {}

    def run(self, program: ProgramNode) -> Dict[str, Any]:
        self.subprograms = {sub.name.lower(): sub for sub in program.subprograms}
        global_frame = Frame()
        self._declare_var_decls(global_frame, program.var_decls)
        for sub in program.subprograms:
            # allow subprogram names to resolve globally if needed
            if sub.kind == 'function':
                global_frame.declare(sub.name, 0)
        self._exec_compound(program.body, global_frame)
        return {
            'output': ''.join(self.output_buffer).rstrip('\n'),
            'warnings': self.runtime_warnings,
        }

    def _runtime_error(self, message: str, node: Optional[ASTNode] = None):
        line = getattr(node, 'line', None) if node is not None else None
        col = getattr(node, 'col', None) if node is not None else None
        raise RuntimeExecutionError(message, line=line, col=col)

    def _default_value(self, type_node: Optional[TypeNode]):
        if type_node and type_node.type_name.startswith('array'):
            low = type_node.low or 0
            high = type_node.high or 0
            size = max(0, high - low + 1)
            return {'low': low, 'high': high, 'data': [0] * size}
        return 0

    def _declare_var_decls(self, frame: Frame, decls: List[VarDeclNode]):
        for decl in decls:
            default = self._default_value(decl.var_type)
            for name in decl.names:
                if isinstance(default, dict):
                    frame.declare(name, {
                        'low': default['low'],
                        'high': default['high'],
                        'data': list(default['data']),
                    })
                else:
                    frame.declare(name, default)

    def _exec_compound(self, node: Optional[CompoundStmt], frame: Frame):
        if node is None:
            return
        for stmt in node.statements:
            self._exec_stmt(stmt, frame)

    def _exec_stmt(self, node: Optional[ASTNode], frame: Frame):
        if node is None:
            return
        if isinstance(node, CompoundStmt):
            self._exec_compound(node, frame)
        elif isinstance(node, AssignStmt):
            value = self._eval_expr(node.value, frame)
            self._assign(node.variable, value, frame)
        elif isinstance(node, IfStmt):
            if self._truthy(self._eval_expr(node.condition, frame)):
                self._exec_stmt(node.then_stmt, frame)
            else:
                self._exec_stmt(node.else_stmt, frame)
        elif isinstance(node, WhileStmt):
            guard = 0
            while self._truthy(self._eval_expr(node.condition, frame)):
                self._exec_stmt(node.body, frame)
                guard += 1
                if guard > 100000:
                    self._runtime_error('Loop exceeded safe execution limit', node)
        elif isinstance(node, ReadStmt):
            for var in node.variables:
                value = self._next_input()
                self._assign(var, value, frame)
        elif isinstance(node, WriteStmt):
            parts = [self._stringify_output_item(item, frame) for item in node.items]
            self.output_buffer.append(''.join(parts) + '\n')
        elif isinstance(node, ProcCallStmt):
            self._call_subprogram(node.name, node.arguments, frame, expect_value=False, caller_node=node)
        else:
            self._runtime_error(f'Unsupported statement: {type(node).__name__}', node)

    def _next_input(self) -> int:
        if self.input_index >= len(self.inputs):
            self.runtime_warnings.append('Not enough input values supplied to read(...); defaulted missing input to 0.')
            return 0
        value = self.inputs[self.input_index]
        self.input_index += 1
        return int(value)

    def _assign(self, var: VariableExpr, value: Any, frame: Frame):
        try:
            cell = frame.resolve_cell(var.name)
        except RuntimeExecutionError:
            self._runtime_error(f"Undeclared identifier '{var.name}'", var)
        if var.index is None:
            cell.value = int(value) if not isinstance(value, dict) else value
            return
        arr = cell.value
        if not isinstance(arr, dict) or 'data' not in arr:
            self._runtime_error(f"'{var.name}' is not an array", var)
        idx = int(self._eval_expr(var.index, frame))
        low, high = arr['low'], arr['high']
        if idx < low or idx > high:
            self._runtime_error(f"Array index {idx} out of bounds for '{var.name}' [{low}..{high}]", var)
        arr['data'][idx - low] = int(value)

    def _eval_expr(self, node: ASTNode, frame: Frame):
        if isinstance(node, IntegerLiteral):
            return int(node.value)
        if isinstance(node, StringLiteral):
            return node.value
        if isinstance(node, VariableExpr):
            try:
                cell = frame.resolve_cell(node.name)
            except RuntimeExecutionError:
                self._runtime_error(f"Undeclared identifier '{node.name}'", node)
            if node.index is None:
                return cell.value
            arr = cell.value
            if not isinstance(arr, dict) or 'data' not in arr:
                self._runtime_error(f"'{node.name}' is not an array", node)
            idx = int(self._eval_expr(node.index, frame))
            low, high = arr['low'], arr['high']
            if idx < low or idx > high:
                self._runtime_error(f"Array index {idx} out of bounds for '{node.name}' [{low}..{high}]", node)
            return arr['data'][idx - low]
        if isinstance(node, UnaryExpr):
            val = self._eval_expr(node.operand, frame)
            if node.op == '-':
                return -int(val)
            if node.op == 'not':
                return 0 if self._truthy(val) else 1
            self._runtime_error(f"Unsupported unary operator '{node.op}'", node)
        if isinstance(node, BinaryExpr):
            left = self._eval_expr(node.left, frame)
            right = self._eval_expr(node.right, frame)
            return self._apply_binary(node, left, right)
        if isinstance(node, FuncCallExpr):
            return self._call_subprogram(node.name, node.arguments, frame, expect_value=True, caller_node=node)
        self._runtime_error(f'Unsupported expression: {type(node).__name__}', node)

    def _apply_binary(self, node: BinaryExpr, left: Any, right: Any):
        op = node.op
        l, r = int(left), int(right)
        if op == '+':
            return l + r
        if op == '-':
            return l - r
        if op == '*':
            return l * r
        if op == '/':
            if r == 0:
                self._runtime_error('Division by zero', node)
            return l // r
        if op == 'and':
            return 1 if self._truthy(l) and self._truthy(r) else 0
        if op == 'or':
            return 1 if self._truthy(l) or self._truthy(r) else 0
        if op == '=':
            return 1 if l == r else 0
        if op == '<>':
            return 1 if l != r else 0
        if op == '<':
            return 1 if l < r else 0
        if op == '<=':
            return 1 if l <= r else 0
        if op == '>':
            return 1 if l > r else 0
        if op == '>=':
            return 1 if l >= r else 0
        self._runtime_error(f"Unsupported operator '{op}'", node)

    def _truthy(self, value: Any) -> bool:
        return int(value) != 0

    def _stringify_output_item(self, item: ASTNode, frame: Frame) -> str:
        value = self._eval_expr(item, frame) if not isinstance(item, StringLiteral) else item.value
        return str(value)

    def _call_subprogram(self, name: str, arguments: List[ASTNode], caller_frame: Frame, expect_value: bool, caller_node: Optional[ASTNode] = None):
        sub = self.subprograms.get(name.lower())
        if sub is None:
            self._runtime_error(f"Undefined subprogram '{name}'", caller_node)

        new_frame = Frame(parent=caller_frame)
        # Pascal return convention
        if sub.kind == 'function':
            new_frame.declare(sub.name, 0)

        arg_values = [self._eval_expr(arg, caller_frame) for arg in arguments]
        arg_i = 0
        for param_decl in sub.params:
            default = self._default_value(param_decl.var_type)
            for param_name in param_decl.names:
                if arg_i >= len(arg_values):
                    self._runtime_error(f"Not enough arguments passed to '{name}'", caller_node)
                new_frame.declare(param_name, int(arg_values[arg_i]) if not isinstance(default, dict) else arg_values[arg_i])
                arg_i += 1
        if arg_i != len(arg_values):
            self._runtime_error(f"Too many arguments passed to '{name}'", caller_node)

        self._declare_var_decls(new_frame, sub.var_decls)
        self._exec_compound(sub.body, new_frame)
        if sub.kind == 'function':
            result = new_frame.resolve_cell(sub.name).value
            return result
        if expect_value:
            self._runtime_error(f"Procedure '{name}' cannot be used in an expression", caller_node)
        return None
