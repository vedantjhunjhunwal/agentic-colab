"""
============================================================
  DSL Compiler – Symbol Table
  Manages scopes, type info, function/procedure signatures
============================================================
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


# ──────────────────────────────────────────────────────────
#  Type descriptors
# ──────────────────────────────────────────────────────────
@dataclass
class TypeDesc:
    name: str

    def __str__(self):
        return self.name

@dataclass
class IntegerType(TypeDesc):
    name: str = "integer"

@dataclass
class ArrayType(TypeDesc):
    low:       int = 0
    high:      int = 0
    elem_type: TypeDesc = field(default_factory=lambda: IntegerType())
    name:      str = ""

    def __post_init__(self):
        self.name = f"array[{self.low}..{self.high}] of {self.elem_type}"

@dataclass
class FunctionType(TypeDesc):
    param_types: List[TypeDesc] = field(default_factory=list)
    return_type: Optional[TypeDesc] = None
    name:        str = "function"

@dataclass
class ProcedureType(TypeDesc):
    param_types: List[TypeDesc] = field(default_factory=list)
    name:        str = "procedure"


# ──────────────────────────────────────────────────────────
#  Symbol entry
# ──────────────────────────────────────────────────────────
@dataclass
class Symbol:
    name:          str
    sym_type:      TypeDesc
    scope_level:   int
    is_param:      bool  = False
    param_index:   int   = -1
    memory_offset: int   = 0
    line_declared: int   = 0


# ──────────────────────────────────────────────────────────
#  Scope (one symbol table per scope)
# ──────────────────────────────────────────────────────────
class Scope:
    def __init__(self, name: str, level: int, parent: Optional['Scope'] = None):
        self.name:    str                   = name
        self.level:   int                   = level
        self.parent:  Optional['Scope']     = parent
        self.symbols: Dict[str, Symbol]     = {}
        self.offset:  int                   = 0       # next available memory offset

    def declare(self, sym: Symbol) -> bool:
        """Returns False if already declared in THIS scope."""
        if sym.name in self.symbols:
            return False
        sym.scope_level   = self.level
        sym.memory_offset = self.offset
        self.offset      += 1
        self.symbols[sym.name] = sym
        return True

    def lookup_local(self, name: str) -> Optional[Symbol]:
        return self.symbols.get(name)

    def lookup(self, name: str) -> Optional[Symbol]:
        """Walk up scope chain."""
        scope: Optional[Scope] = self
        while scope is not None:
            sym = scope.symbols.get(name)
            if sym is not None:
                return sym
            scope = scope.parent
        return None


# ──────────────────────────────────────────────────────────
#  Symbol Table (stack of scopes)
# ──────────────────────────────────────────────────────────
class SymbolTable:
    def __init__(self):
        self.global_scope  = Scope("global", 0)
        self.current_scope = self.global_scope
        self.scope_stack:  List[Scope] = [self.global_scope]
        self.errors:       List[str]   = []

    # ── Scope management ──────────────────────────────────
    def enter_scope(self, name: str):
        new_scope = Scope(name, len(self.scope_stack), self.current_scope)
        self.scope_stack.append(new_scope)
        self.current_scope = new_scope

    def exit_scope(self) -> Scope:
        if len(self.scope_stack) <= 1:
            raise RuntimeError("Cannot exit global scope")
        finished = self.scope_stack.pop()
        self.current_scope = self.scope_stack[-1]
        return finished

    # ── Symbol operations ─────────────────────────────────
    def declare(self, name: str, sym_type: TypeDesc, line: int, is_param: bool = False, param_index: int = -1) -> bool:
        sym = Symbol(
            name=name,
            sym_type=sym_type,
            scope_level=self.current_scope.level,
            is_param=is_param,
            param_index=param_index,
            line_declared=line
        )
        ok = self.current_scope.declare(sym)
        if not ok:
            self.errors.append(f"[SEM ERROR] Line {line}: Identifier '{name}' already declared in this scope")
        return ok

    def lookup(self, name: str) -> Optional[Symbol]:
        return self.current_scope.lookup(name)

    def lookup_local(self, name: str) -> Optional[Symbol]:
        return self.current_scope.lookup_local(name)

    # ── Pretty print ──────────────────────────────────────
    def dump(self):
        print("\n" + "═" * 70)
        print("  SYMBOL TABLE DUMP")
        print("═" * 70)
        self._dump_scope(self.global_scope, 0)
        print("═" * 70)

    def _dump_scope(self, scope: Scope, indent: int):
        pad = "  " * indent
        print(f"{pad}Scope: {scope.name!r}  (level {scope.level})")
        print(f"{pad}  {'NAME':<20} {'TYPE':<30} {'OFFSET':>6} {'LINE':>5}")
        print(f"{pad}  {'-'*20} {'-'*30} {'-'*6} {'-'*5}")
        for name, sym in scope.symbols.items():
            print(f"{pad}  {name:<20} {str(sym.sym_type):<30} {sym.memory_offset:>6} {sym.line_declared:>5}")
