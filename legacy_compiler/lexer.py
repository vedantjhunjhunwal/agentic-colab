"""
============================================================
  DSL / Programming Language Compiler – Phase 1: LEXER
  Lexical Analyzer (Tokenizer)
  Author : Compiler Design Project
  Language: Pascal-like DSL as per Assignment Guidelines
============================================================
"""

from enum import Enum, auto
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# ──────────────────────────────────────────────────────────
#  Token Types
# ──────────────────────────────────────────────────────────
class TokenType(Enum):
    # Literals
    INTEGER_LITERAL  = auto()
    STRING_LITERAL   = auto()

    # Identifiers & Reserved Words
    IDENTIFIER       = auto()
    RESERVED_WORD    = auto()

    # Single-char delimiters
    LPAREN    = auto()   # (
    RPAREN    = auto()   # )
    LBRACKET  = auto()   # [
    RBRACKET  = auto()   # ]
    SEMICOLON = auto()   # ;
    COLON     = auto()   # :
    DOT       = auto()   # .
    COMMA     = auto()   # ,
    STAR      = auto()   # *
    MINUS     = auto()   # -
    PLUS      = auto()   # +
    SLASH     = auto()   # /
    LT        = auto()   # <
    EQUALS    = auto()   # =
    GT        = auto()   # >

    # Compound delimiters
    NEQ       = auto()   # <>
    ASSIGN    = auto()   # :=
    LEQ       = auto()   # <=
    GEQ       = auto()   # >=
    DOTDOT    = auto()   # ..

    # Special
    EOF       = auto()
    ERROR     = auto()


# ──────────────────────────────────────────────────────────
#  Reserved Words  (case-insensitive)
# ──────────────────────────────────────────────────────────
RESERVED_WORDS = {
    "and", "array", "begin", "integer", "do", "else", "end",
    "function", "if", "of", "or", "not", "procedure", "program",
    "read", "then", "var", "while", "write"
}


# ──────────────────────────────────────────────────────────
#  Token dataclass
# ──────────────────────────────────────────────────────────
@dataclass
class Token:
    type:   TokenType
    value:  str
    line:   int
    column: int

    def __repr__(self):
        return (f"Token({self.type.name!r:20s}, "
                f"value={self.value!r:20s}, "
                f"line={self.line}, col={self.column})")


# ──────────────────────────────────────────────────────────
#  Lexer Error
# ──────────────────────────────────────────────────────────
@dataclass
class LexError:
    message: str
    line:    int
    column:  int

    def __str__(self):
        return f"[LEX ERROR] Line {self.line}, Col {self.column}: {self.message}"


# ──────────────────────────────────────────────────────────
#  Lexer Class
# ──────────────────────────────────────────────────────────
class Lexer:
    MAX_IDENT_LEN = 32  # Only first 32 chars are significant

    def __init__(self, source: str):
        self.source  : str        = source
        self.pos     : int        = 0
        self.line    : int        = 1
        self.column  : int        = 1
        self.tokens  : List[Token]    = []
        self.errors  : List[LexError] = []

    # ── Low-level helpers ──────────────────────────────────
    def _current(self) -> Optional[str]:
        if self.pos < len(self.source):
            return self.source[self.pos]
        return None

    def _peek(self, offset: int = 1) -> Optional[str]:
        idx = self.pos + offset
        if idx < len(self.source):
            return self.source[idx]
        return None

    def _advance(self) -> str:
        ch = self.source[self.pos]
        self.pos += 1
        if ch == '\n':
            self.line  += 1
            self.column = 1
        else:
            self.column += 1
        return ch

    def _skip_whitespace_and_comments(self):
        while self.pos < len(self.source):
            ch = self._current()
            if ch in (' ', '\t', '\r', '\n'):
                self._advance()
            elif ch == '!':          # comment → skip to end of line
                while self.pos < len(self.source) and self._current() != '\n':
                    self._advance()
            else:
                break

    # ── Token scanners ────────────────────────────────────
    def _scan_identifier_or_keyword(self, line: int, col: int) -> Token:
        buf = []
        while self.pos < len(self.source) and (self._current().isalpha() or self._current().isdigit()):
            buf.append(self._advance())
        raw   = ''.join(buf)
        lower = raw.lower()
        # Only first 32 chars are significant
        key   = lower[:self.MAX_IDENT_LEN]
        if key in RESERVED_WORDS:
            return Token(TokenType.RESERVED_WORD, key, line, col)
        return Token(TokenType.IDENTIFIER, key, line, col)

    def _scan_integer(self, line: int, col: int) -> Token:
        buf = []
        while self.pos < len(self.source) and self._current().isdigit():
            buf.append(self._advance())
        return Token(TokenType.INTEGER_LITERAL, ''.join(buf), line, col)

    def _scan_string(self, line: int, col: int) -> Tuple[Token, Optional[LexError]]:
        """Scan a quoted string starting with apostrophe."""
        self._advance()   # consume opening '
        buf   = []
        error = None
        while self.pos < len(self.source):
            ch = self._current()
            if ch == '\n':
                error = LexError("Unterminated string literal (newline in string)", line, col)
                break
            if ch == '\\':          # escape sequence
                self._advance()     # consume backslash
                nxt = self._current()
                if nxt is None:
                    error = LexError("Unexpected end-of-file in escape sequence", line, col)
                    break
                self._advance()
                if   nxt == 'n': buf.append('\n')
                elif nxt == 't': buf.append('\t')
                else:            buf.append(nxt)   # \' → ' , \\ → \  etc.
            elif ch == "'":
                self._advance()    # consume closing '
                return Token(TokenType.STRING_LITERAL, ''.join(buf), line, col), None
            else:
                buf.append(self._advance())
        if error is None:
            error = LexError("Unterminated string literal (EOF)", line, col)
        return Token(TokenType.ERROR, ''.join(buf), line, col), error

    # ── Main tokenizer ────────────────────────────────────
    def tokenize(self) -> Tuple[List[Token], List[LexError]]:
        while True:
            self._skip_whitespace_and_comments()
            if self.pos >= len(self.source):
                self.tokens.append(Token(TokenType.EOF, '', self.line, self.column))
                break

            line = self.line
            col  = self.column
            ch   = self._current()

            # Identifier / keyword
            if ch.isalpha():
                self.tokens.append(self._scan_identifier_or_keyword(line, col))
                continue

            # Integer
            if ch.isdigit():
                self.tokens.append(self._scan_integer(line, col))
                continue

            # String
            if ch == "'":
                tok, err = self._scan_string(line, col)
                self.tokens.append(tok)
                if err:
                    self.errors.append(err)
                continue

            # Compound delimiters / single-char delimiters
            self._advance()   # consume ch

            if ch == ':':
                if self._current() == '=':
                    self._advance()
                    self.tokens.append(Token(TokenType.ASSIGN, ':=', line, col))
                else:
                    self.tokens.append(Token(TokenType.COLON, ':', line, col))

            elif ch == '<':
                if self._current() == '>':
                    self._advance()
                    self.tokens.append(Token(TokenType.NEQ, '<>', line, col))
                elif self._current() == '=':
                    self._advance()
                    self.tokens.append(Token(TokenType.LEQ, '<=', line, col))
                else:
                    self.tokens.append(Token(TokenType.LT, '<', line, col))

            elif ch == '>':
                if self._current() == '=':
                    self._advance()
                    self.tokens.append(Token(TokenType.GEQ, '>=', line, col))
                else:
                    self.tokens.append(Token(TokenType.GT, '>', line, col))

            elif ch == '.':
                if self._current() == '.':
                    self._advance()
                    self.tokens.append(Token(TokenType.DOTDOT, '..', line, col))
                else:
                    self.tokens.append(Token(TokenType.DOT, '.', line, col))

            elif ch == '(': self.tokens.append(Token(TokenType.LPAREN,    '(', line, col))
            elif ch == ')': self.tokens.append(Token(TokenType.RPAREN,    ')', line, col))
            elif ch == '[': self.tokens.append(Token(TokenType.LBRACKET,  '[', line, col))
            elif ch == ']': self.tokens.append(Token(TokenType.RBRACKET,  ']', line, col))
            elif ch == ';': self.tokens.append(Token(TokenType.SEMICOLON, ';', line, col))
            elif ch == ',': self.tokens.append(Token(TokenType.COMMA,     ',', line, col))
            elif ch == '*': self.tokens.append(Token(TokenType.STAR,      '*', line, col))
            elif ch == '-': self.tokens.append(Token(TokenType.MINUS,     '-', line, col))
            elif ch == '+': self.tokens.append(Token(TokenType.PLUS,      '+', line, col))
            elif ch == '/': self.tokens.append(Token(TokenType.SLASH,     '/', line, col))
            elif ch == '=': self.tokens.append(Token(TokenType.EQUALS,    '=', line, col))

            else:
                err = LexError(f"Illegal character {ch!r}", line, col)
                self.errors.append(err)
                self.tokens.append(Token(TokenType.ERROR, ch, line, col))

        return self.tokens, self.errors


# ──────────────────────────────────────────────────────────
#  Pretty-print token table
# ──────────────────────────────────────────────────────────
def print_token_table(tokens: List[Token]):
    print("\n" + "═" * 70)
    print(f"  {'TYPE':<22} {'VALUE':<25} {'LINE':>5} {'COL':>5}")
    print("═" * 70)
    for tok in tokens:
        print(f"  {tok.type.name:<22} {tok.value!r:<25} {tok.line:>5} {tok.column:>5}")
    print("═" * 70)
