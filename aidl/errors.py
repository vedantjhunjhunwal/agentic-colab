"""Error types for the AIDL v2 language.

Every error carries a line (1-based) and column so the notebook UI and the
agentic assistant can point users at the exact problem.
"""
from __future__ import annotations


class AIDLError(Exception):
    """Base class for all AIDL errors."""

    kind = "Error"

    def __init__(self, message: str, line: int = 0, col: int = 0):
        self.message = message
        self.line = line
        self.col = col
        super().__init__(message)

    def __str__(self) -> str:
        if self.line:
            return f"{self.kind} (line {self.line}): {self.message}"
        return f"{self.kind}: {self.message}"


class AIDLSyntaxError(AIDLError):
    kind = "SyntaxError"


class AIDLNameError(AIDLError):
    kind = "NameError"


class AIDLTypeError(AIDLError):
    kind = "TypeError"


class AIDLValueError(AIDLError):
    kind = "ValueError"


class AIDLRuntimeError(AIDLError):
    kind = "RuntimeError"
