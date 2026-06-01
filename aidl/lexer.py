"""Tokenizer for AIDL v2.

AIDL v2 is a small, Python-like language. The lexer emits a flat token stream
including synthetic INDENT / DEDENT / NEWLINE tokens (just like CPython's
tokenizer) so the parser can stay a clean recursive-descent implementation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .errors import AIDLSyntaxError

KEYWORDS = {
    "if", "elif", "else", "for", "while", "in", "and", "or", "not",
    "print", "true", "false", "none", "break", "continue", "return",
    "def", "let",
}

# Multi-char operators must be tried before single-char ones.
THREE_CHAR_OPS = ("**=", "//=")
TWO_CHAR_OPS = ("**", "//", "==", "!=", "<=", ">=", "+=", "-=", "*=", "/=", "->")
ONE_CHAR_OPS = set("+-*/%=<>(){}[],:.")


@dataclass
class Token:
    type: str          # NUMBER, STRING, NAME, KEYWORD, OP, NEWLINE, INDENT, DEDENT, EOF
    value: object
    line: int
    col: int

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"Token({self.type}, {self.value!r}, L{self.line}:{self.col})"


class Lexer:
    def __init__(self, source: str):
        # Normalise newlines and guarantee a trailing newline.
        self.source = source.replace("\r\n", "\n").replace("\r", "\n")
        if not self.source.endswith("\n"):
            self.source += "\n"
        self.tokens: List[Token] = []

    def tokenize(self) -> List[Token]:
        lines = self.source.split("\n")
        indent_stack = [0]
        paren_depth = 0
        # We process logical lines; blank / comment-only lines don't affect indent.
        for lineno, raw in enumerate(lines, start=1):
            # Skip a phantom final empty element produced by the trailing newline.
            if lineno == len(lines) and raw == "":
                continue

            # Compute leading indentation (spaces + tabs->4) only when not inside parens.
            if paren_depth == 0:
                stripped = raw.lstrip(" \t")
                # Blank or comment-only line: ignore for indentation purposes.
                if stripped == "" or stripped.startswith("#"):
                    continue
                indent = self._indent_width(raw)
                if indent > indent_stack[-1]:
                    indent_stack.append(indent)
                    self.tokens.append(Token("INDENT", indent, lineno, 1))
                while indent < indent_stack[-1]:
                    indent_stack.pop()
                    self.tokens.append(Token("DEDENT", indent, lineno, 1))
                if indent != indent_stack[-1]:
                    raise AIDLSyntaxError(
                        "inconsistent indentation", lineno, indent + 1
                    )

            paren_depth = self._tokenize_line(raw, lineno, paren_depth)

            # End of a logical line (only when balanced) → NEWLINE.
            if paren_depth == 0 and self.tokens and self.tokens[-1].type not in ("NEWLINE", "INDENT", "DEDENT"):
                self.tokens.append(Token("NEWLINE", "\n", lineno, len(raw) + 1))

        # Close any remaining open blocks.
        while len(indent_stack) > 1:
            indent_stack.pop()
            self.tokens.append(Token("DEDENT", 0, len(lines), 1))
        self.tokens.append(Token("EOF", None, len(lines), 1))
        return self.tokens

    @staticmethod
    def _indent_width(raw: str) -> int:
        width = 0
        for ch in raw:
            if ch == " ":
                width += 1
            elif ch == "\t":
                width += 4 - (width % 4)
            else:
                break
        return width

    def _tokenize_line(self, raw: str, lineno: int, paren_depth: int) -> int:
        i = 0
        n = len(raw)
        while i < n:
            ch = raw[i]
            col = i + 1

            # Whitespace inside a line.
            if ch in " \t":
                i += 1
                continue

            # Comment to end of line.
            if ch == "#":
                break

            # String literal (single or double quoted), no escapes beyond \n \t \" \' \\.
            if ch in "\"'":
                value, i = self._read_string(raw, i, lineno)
                self.tokens.append(Token("STRING", value, lineno, col))
                continue

            # Number (int or float).
            if ch.isdigit() or (ch == "." and i + 1 < n and raw[i + 1].isdigit()):
                value, i = self._read_number(raw, i, lineno)
                self.tokens.append(Token("NUMBER", value, lineno, col))
                continue

            # Identifier or keyword.
            if ch.isalpha() or ch == "_":
                j = i
                while j < n and (raw[j].isalnum() or raw[j] == "_"):
                    j += 1
                word = raw[i:j]
                low = word.lower()
                if low in KEYWORDS:
                    self.tokens.append(Token("KEYWORD", low, lineno, col))
                else:
                    self.tokens.append(Token("NAME", word, lineno, col))
                i = j
                continue

            # Operators (longest match first).
            three = raw[i:i + 3]
            if three in THREE_CHAR_OPS:
                self.tokens.append(Token("OP", three, lineno, col))
                i += 3
                continue
            two = raw[i:i + 2]
            if two in TWO_CHAR_OPS:
                self.tokens.append(Token("OP", two, lineno, col))
                i += 2
                continue
            if ch in ONE_CHAR_OPS:
                if ch in "([{":
                    paren_depth += 1
                elif ch in ")]}":
                    paren_depth = max(0, paren_depth - 1)
                self.tokens.append(Token("OP", ch, lineno, col))
                i += 1
                continue

            raise AIDLSyntaxError(f"unexpected character {ch!r}", lineno, col)
        return paren_depth

    def _read_string(self, raw: str, i: int, lineno: int):
        quote = raw[i]
        i += 1
        out = []
        n = len(raw)
        while i < n and raw[i] != quote:
            c = raw[i]
            if c == "\\" and i + 1 < n:
                nxt = raw[i + 1]
                out.append({"n": "\n", "t": "\t", '"': '"', "'": "'", "\\": "\\"}.get(nxt, nxt))
                i += 2
                continue
            out.append(c)
            i += 1
        if i >= n:
            raise AIDLSyntaxError("unterminated string literal", lineno, i)
        return "".join(out), i + 1

    def _read_number(self, raw: str, i: int, lineno: int):
        j = i
        n = len(raw)
        is_float = False
        while j < n and (raw[j].isdigit() or raw[j] == "."):
            if raw[j] == ".":
                if is_float:
                    break
                is_float = True
            j += 1
        text = raw[i:j]
        try:
            value = float(text) if is_float else int(text)
        except ValueError:
            raise AIDLSyntaxError(f"invalid number {text!r}", lineno, i + 1)
        return value, j
