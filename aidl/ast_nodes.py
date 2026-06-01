"""AST node definitions for AIDL v2.

Plain dataclasses; every node keeps a line number for precise error reporting.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Node:
    line: int = 0


# ---- Expressions -----------------------------------------------------------
@dataclass
class Literal(Node):
    value: object = None


@dataclass
class Name(Node):
    ident: str = ""


@dataclass
class ListExpr(Node):
    elements: List[Node] = field(default_factory=list)


@dataclass
class Unary(Node):
    op: str = ""
    operand: Optional[Node] = None


@dataclass
class Binary(Node):
    op: str = ""
    left: Optional[Node] = None
    right: Optional[Node] = None


@dataclass
class Logical(Node):
    op: str = ""           # 'and' / 'or'
    left: Optional[Node] = None
    right: Optional[Node] = None


@dataclass
class Compare(Node):
    op: str = ""
    left: Optional[Node] = None
    right: Optional[Node] = None


@dataclass
class Call(Node):
    func: Optional[Node] = None
    args: List[Node] = field(default_factory=list)
    kwargs: dict = field(default_factory=dict)   # name -> Node


@dataclass
class Index(Node):
    target: Optional[Node] = None
    index: Optional[Node] = None


@dataclass
class Attribute(Node):
    target: Optional[Node] = None
    attr: str = ""


# ---- Statements ------------------------------------------------------------
@dataclass
class Assign(Node):
    target: Optional[Node] = None   # Name or Index
    op: str = "="                   # '=', '+=', ...
    value: Optional[Node] = None


@dataclass
class ExprStmt(Node):
    value: Optional[Node] = None


@dataclass
class Print(Node):
    args: List[Node] = field(default_factory=list)


@dataclass
class If(Node):
    test: Optional[Node] = None
    body: List[Node] = field(default_factory=list)
    orelse: List[Node] = field(default_factory=list)   # may contain another If (elif)


@dataclass
class While(Node):
    test: Optional[Node] = None
    body: List[Node] = field(default_factory=list)


@dataclass
class For(Node):
    var: str = ""
    iterable: Optional[Node] = None
    body: List[Node] = field(default_factory=list)


@dataclass
class Break(Node):
    pass


@dataclass
class Continue(Node):
    pass


@dataclass
class FuncDef(Node):
    name: str = ""
    params: List[tuple] = field(default_factory=list)   # (name, default_node_or_None)
    body: List[Node] = field(default_factory=list)


@dataclass
class Return(Node):
    value: Optional[Node] = None


@dataclass
class Program(Node):
    body: List[Node] = field(default_factory=list)
