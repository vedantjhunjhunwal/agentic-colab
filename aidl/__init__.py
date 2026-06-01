"""AIDL v2 — an upgraded, Python-like AI workflow DSL.

Public surface:

    from aidl import run_source, parse
    from aidl import AIDLError, Interpreter
"""
from .errors import (
    AIDLError,
    AIDLNameError,
    AIDLRuntimeError,
    AIDLSyntaxError,
    AIDLTypeError,
    AIDLValueError,
)
from .interpreter import Dataset, Interpreter, Model, run_source
from .parser import parse

__all__ = [
    "run_source", "parse", "Interpreter", "Dataset", "Model",
    "AIDLError", "AIDLSyntaxError", "AIDLNameError",
    "AIDLTypeError", "AIDLValueError", "AIDLRuntimeError",
]
