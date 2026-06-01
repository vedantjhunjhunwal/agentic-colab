"""
============================================================
  DSL Compiler – AST Node Definitions
  Abstract Syntax Tree nodes produced by the Parser
============================================================
"""

from dataclasses import dataclass, field
from typing import List, Optional, Any


# ──────────────────────────────────────────────────────────
#  Base
# ──────────────────────────────────────────────────────────
@dataclass
class ASTNode:
    line: int = 0
    col:  int = 0

    def accept(self, visitor):
        method = getattr(visitor, f"visit_{type(self).__name__}", visitor.visit_generic)
        return method(self)


# ──────────────────────────────────────────────────────────
#  Program structure
# ──────────────────────────────────────────────────────────
@dataclass
class ProgramNode(ASTNode):
    name:        str                = ""
    var_decls:   List['VarDeclNode']       = field(default_factory=list)
    subprograms: List['SubprogramNode']    = field(default_factory=list)
    body:        Optional['CompoundStmt']  = None


@dataclass
class VarDeclNode(ASTNode):
    names:   List[str]          = field(default_factory=list)
    var_type: Optional['TypeNode'] = None


@dataclass
class TypeNode(ASTNode):
    type_name: str = "integer"
    low:       Optional[int] = None
    high:      Optional[int] = None


@dataclass
class SubprogramNode(ASTNode):
    kind:       str = "procedure"   # "function" or "procedure"
    name:       str = ""
    params:     List['VarDeclNode'] = field(default_factory=list)
    return_type: Optional[str]      = None
    var_decls:  List['VarDeclNode'] = field(default_factory=list)
    body:       Optional['CompoundStmt'] = None


# ──────────────────────────────────────────────────────────
#  Statements
# ──────────────────────────────────────────────────────────
@dataclass
class CompoundStmt(ASTNode):
    statements: List[ASTNode] = field(default_factory=list)


@dataclass
class AssignStmt(ASTNode):
    variable: 'VariableExpr'    = field(default_factory=lambda: VariableExpr())
    value:    ASTNode           = field(default_factory=lambda: ASTNode())


@dataclass
class IfStmt(ASTNode):
    condition: ASTNode    = field(default_factory=lambda: ASTNode())
    then_stmt: ASTNode    = field(default_factory=lambda: ASTNode())
    else_stmt: Optional[ASTNode] = None


@dataclass
class WhileStmt(ASTNode):
    condition: ASTNode = field(default_factory=lambda: ASTNode())
    body:      ASTNode = field(default_factory=lambda: ASTNode())


@dataclass
class ReadStmt(ASTNode):
    variables: List['VariableExpr'] = field(default_factory=list)


@dataclass
class WriteStmt(ASTNode):
    items: List[ASTNode] = field(default_factory=list)


@dataclass
class ProcCallStmt(ASTNode):
    name:      str          = ""
    arguments: List[ASTNode] = field(default_factory=list)


# ──────────────────────────────────────────────────────────
#  Expressions
# ──────────────────────────────────────────────────────────
@dataclass
class BinaryExpr(ASTNode):
    op:    str     = ""
    left:  ASTNode = field(default_factory=lambda: ASTNode())
    right: ASTNode = field(default_factory=lambda: ASTNode())


@dataclass
class UnaryExpr(ASTNode):
    op:      str     = ""
    operand: ASTNode = field(default_factory=lambda: ASTNode())


@dataclass
class VariableExpr(ASTNode):
    name:  str              = ""
    index: Optional[ASTNode] = None   # for array subscript


@dataclass
class IntegerLiteral(ASTNode):
    value: int = 0


@dataclass
class StringLiteral(ASTNode):
    value: str = ""


@dataclass
class FuncCallExpr(ASTNode):
    name:      str           = ""
    arguments: List[ASTNode] = field(default_factory=list)


# ──────────────────────────────────────────────────────────
#  AST pretty printer
# ──────────────────────────────────────────────────────────
class ASTPrinter:
    def __init__(self):
        self._indent = 0

    def _pad(self):
        return "  " * self._indent

    def print(self, node: ASTNode):
        if node is None:
            print(self._pad() + "<None>")
            return
        name = type(node).__name__
        print(self._pad() + f"[{name}]  line={node.line}")
        self._indent += 1
        for attr, val in vars(node).items():
            if attr in ('line', 'col'):
                continue
            if isinstance(val, ASTNode):
                print(self._pad() + f"{attr}:")
                self._indent += 1
                self.print(val)
                self._indent -= 1
            elif isinstance(val, list):
                print(self._pad() + f"{attr}: [")
                self._indent += 1
                for item in val:
                    if isinstance(item, ASTNode):
                        self.print(item)
                    else:
                        print(self._pad() + repr(item))
                self._indent -= 1
                print(self._pad() + "]")
            else:
                print(self._pad() + f"{attr} = {val!r}")
        self._indent -= 1
