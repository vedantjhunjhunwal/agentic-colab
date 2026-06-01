"""Recursive-descent parser for AIDL v2.

Grammar (informal):

    program     := statement*
    statement   := compound | simple NEWLINE
    compound    := if_stmt | for_stmt | while_stmt
    simple      := assignment | print_stmt | break | continue | expr
    assignment  := target ('='|'+='|'-='|'*='|'/=') expr
    suite       := NEWLINE INDENT statement+ DEDENT | simple NEWLINE

Expression precedence (low -> high): or, and, not, comparison,
add/sub, mul/div/mod, unary, power, call/index/attribute, atom.
"""
from __future__ import annotations

from typing import List

from . import ast_nodes as A
from .errors import AIDLSyntaxError
from .lexer import Lexer, Token

COMPARE_OPS = {"==", "!=", "<", "<=", ">", ">="}
AUG_OPS = {"+=", "-=", "*=", "/="}


class Parser:
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0

    # ---- token helpers ----------------------------------------------------
    @property
    def cur(self) -> Token:
        return self.tokens[self.pos]

    def advance(self) -> Token:
        tok = self.tokens[self.pos]
        if tok.type != "EOF":
            self.pos += 1
        return tok

    def check(self, type_: str, value=None) -> bool:
        t = self.cur
        if t.type != type_:
            return False
        return value is None or t.value == value

    def match(self, type_: str, value=None) -> bool:
        if self.check(type_, value):
            self.advance()
            return True
        return False

    def expect(self, type_: str, value=None, what: str = "") -> Token:
        if self.check(type_, value):
            return self.advance()
        t = self.cur
        wanted = what or (f"{value!r}" if value else type_)
        got = "end of input" if t.type == "EOF" else f"{t.value!r}"
        raise AIDLSyntaxError(f"expected {wanted} but found {got}", t.line, t.col)

    def skip_newlines(self):
        while self.cur.type == "NEWLINE":
            self.advance()

    # ---- entry point ------------------------------------------------------
    def parse(self) -> A.Program:
        body: List[A.Node] = []
        self.skip_newlines()
        while self.cur.type != "EOF":
            body.append(self.statement())
            self.skip_newlines()
        return A.Program(line=1, body=body)

    # ---- statements -------------------------------------------------------
    def statement(self) -> A.Node:
        t = self.cur
        if t.type == "KEYWORD":
            if t.value == "if":
                return self.if_stmt()
            if t.value == "for":
                return self.for_stmt()
            if t.value == "while":
                return self.while_stmt()
            if t.value == "print":
                node = self.print_stmt()
                self.end_simple()
                return node
            if t.value == "break":
                self.advance()
                self.end_simple()
                return A.Break(line=t.line)
            if t.value == "continue":
                self.advance()
                self.end_simple()
                return A.Continue(line=t.line)
            if t.value == "def":
                return self.func_def()
            if t.value == "return":
                return self.return_stmt()
            if t.value == "let":
                # 'let x = ...' is sugar for assignment
                self.advance()
        return self.simple_or_assign()

    def func_def(self) -> A.FuncDef:
        t = self.expect("KEYWORD", "def", "def")
        name_tok = self.expect("NAME", what="function name")
        self.expect("OP", "(", "(")
        params = []
        if not self.check("OP", ")"):
            while True:
                pname = self.expect("NAME", what="parameter name")
                default = None
                if self.match("OP", "="):
                    default = self.expression()
                params.append((pname.value, default))
                if self.match("OP", ","):
                    continue
                break
        self.expect("OP", ")", ")")
        body = self.suite()
        return A.FuncDef(line=t.line, name=name_tok.value, params=params, body=body)

    def return_stmt(self) -> A.Return:
        t = self.expect("KEYWORD", "return", "return")
        value = None
        if self.cur.type not in ("NEWLINE", "EOF", "DEDENT"):
            value = self.expression()
        self.end_simple()
        return A.Return(line=t.line, value=value)

    def end_simple(self):
        if self.cur.type in ("NEWLINE", "EOF", "DEDENT"):
            if self.cur.type == "NEWLINE":
                self.advance()
            return
        t = self.cur
        raise AIDLSyntaxError(
            f"unexpected {t.value!r}; statements end at the line break", t.line, t.col
        )

    def simple_or_assign(self) -> A.Node:
        start = self.cur
        expr = self.expression()
        # Assignment?
        if self.cur.type == "OP" and (self.cur.value == "=" or self.cur.value in AUG_OPS):
            op = self.advance().value
            if not isinstance(expr, (A.Name, A.Index)):
                raise AIDLSyntaxError(
                    "left side of assignment must be a variable or list item",
                    start.line, start.col,
                )
            value = self.expression()
            node = A.Assign(line=start.line, target=expr, op=op, value=value)
            self.end_simple()
            return node
        node = A.ExprStmt(line=start.line, value=expr)
        self.end_simple()
        return node

    def print_stmt(self) -> A.Print:
        t = self.expect("KEYWORD", "print")
        self.expect("OP", "(", "'(' after print")
        args = []
        if not self.check("OP", ")"):
            args.append(self.expression())
            while self.match("OP", ","):
                if self.check("OP", ")"):
                    break
                args.append(self.expression())
        self.expect("OP", ")", "')'")
        return A.Print(line=t.line, args=args)

    def suite(self) -> List[A.Node]:
        self.expect("OP", ":", "':'")
        if self.cur.type == "NEWLINE":
            self.advance()
            self.expect("INDENT", what="an indented block")
            body = []
            self.skip_newlines()
            while self.cur.type not in ("DEDENT", "EOF"):
                body.append(self.statement())
                self.skip_newlines()
            self.expect("DEDENT", what="end of the indented block")
            if not body:
                raise AIDLSyntaxError("indented block is empty", self.cur.line, self.cur.col)
            return body
        # Single-line suite:  if x: print(x)
        return [self.statement()]

    def if_stmt(self) -> A.If:
        t = self.expect("KEYWORD", "if")
        test = self.expression()
        body = self.suite()
        orelse: List[A.Node] = []
        self.skip_newlines()
        if self.check("KEYWORD", "elif"):
            orelse = [self.if_stmt_as_elif()]
        elif self.check("KEYWORD", "else"):
            self.advance()
            orelse = self.suite()
        return A.If(line=t.line, test=test, body=body, orelse=orelse)

    def if_stmt_as_elif(self) -> A.If:
        t = self.expect("KEYWORD", "elif")
        test = self.expression()
        body = self.suite()
        orelse: List[A.Node] = []
        self.skip_newlines()
        if self.check("KEYWORD", "elif"):
            orelse = [self.if_stmt_as_elif()]
        elif self.check("KEYWORD", "else"):
            self.advance()
            orelse = self.suite()
        return A.If(line=t.line, test=test, body=body, orelse=orelse)

    def while_stmt(self) -> A.While:
        t = self.expect("KEYWORD", "while")
        test = self.expression()
        body = self.suite()
        return A.While(line=t.line, test=test, body=body)

    def for_stmt(self) -> A.For:
        t = self.expect("KEYWORD", "for")
        var = self.expect("NAME", what="a loop variable").value
        self.expect("KEYWORD", "in", "'in'")
        iterable = self.expression()
        body = self.suite()
        return A.For(line=t.line, var=var, iterable=iterable, body=body)

    # ---- expressions ------------------------------------------------------
    def expression(self) -> A.Node:
        return self.or_expr()

    def or_expr(self) -> A.Node:
        node = self.and_expr()
        while self.check("KEYWORD", "or"):
            t = self.advance()
            right = self.and_expr()
            node = A.Logical(line=t.line, op="or", left=node, right=right)
        return node

    def and_expr(self) -> A.Node:
        node = self.not_expr()
        while self.check("KEYWORD", "and"):
            t = self.advance()
            right = self.not_expr()
            node = A.Logical(line=t.line, op="and", left=node, right=right)
        return node

    def not_expr(self) -> A.Node:
        if self.check("KEYWORD", "not"):
            t = self.advance()
            operand = self.not_expr()
            return A.Unary(line=t.line, op="not", operand=operand)
        return self.comparison()

    def comparison(self) -> A.Node:
        node = self.arith()
        while self.cur.type == "OP" and self.cur.value in COMPARE_OPS:
            t = self.advance()
            right = self.arith()
            node = A.Compare(line=t.line, op=t.value, left=node, right=right)
        return node

    def arith(self) -> A.Node:
        node = self.term()
        while self.cur.type == "OP" and self.cur.value in ("+", "-"):
            t = self.advance()
            right = self.term()
            node = A.Binary(line=t.line, op=t.value, left=node, right=right)
        return node

    def term(self) -> A.Node:
        node = self.factor()
        while self.cur.type == "OP" and self.cur.value in ("*", "/", "//", "%"):
            t = self.advance()
            right = self.factor()
            node = A.Binary(line=t.line, op=t.value, left=node, right=right)
        return node

    def factor(self) -> A.Node:
        if self.cur.type == "OP" and self.cur.value in ("-", "+"):
            t = self.advance()
            operand = self.factor()
            return A.Unary(line=t.line, op=t.value, operand=operand)
        return self.power()

    def power(self) -> A.Node:
        node = self.trailer_expr()
        if self.cur.type == "OP" and self.cur.value == "**":
            t = self.advance()
            right = self.factor()
            return A.Binary(line=t.line, op="**", left=node, right=right)
        return node

    def trailer_expr(self) -> A.Node:
        node = self.atom()
        while True:
            t = self.cur
            if t.type == "OP" and t.value == "(":
                self.advance()
                args, kwargs = self.arglist()
                self.expect("OP", ")", "')'")
                node = A.Call(line=t.line, func=node, args=args, kwargs=kwargs)
            elif t.type == "OP" and t.value == "[":
                self.advance()
                idx = self.expression()
                self.expect("OP", "]", "']'")
                node = A.Index(line=t.line, target=node, index=idx)
            elif t.type == "OP" and t.value == ".":
                self.advance()
                attr = self.expect("NAME", what="an attribute name").value
                node = A.Attribute(line=t.line, target=node, attr=attr)
            else:
                break
        return node

    def arglist(self):
        args: List[A.Node] = []
        kwargs: dict = {}
        if self.check("OP", ")"):
            return args, kwargs
        self._one_arg(args, kwargs)
        while self.match("OP", ","):
            if self.check("OP", ")"):
                break
            self._one_arg(args, kwargs)
        return args, kwargs

    def _one_arg(self, args, kwargs):
        # keyword arg:  name = expr
        if self.cur.type == "NAME" and self.tokens[self.pos + 1].type == "OP" \
                and self.tokens[self.pos + 1].value == "=":
            name = self.advance().value
            self.advance()  # '='
            kwargs[name] = self.expression()
        else:
            if kwargs:
                raise AIDLSyntaxError(
                    "positional argument cannot follow a keyword argument",
                    self.cur.line, self.cur.col,
                )
            args.append(self.expression())

    def atom(self) -> A.Node:
        t = self.cur
        if t.type == "NUMBER":
            self.advance()
            return A.Literal(line=t.line, value=t.value)
        if t.type == "STRING":
            self.advance()
            return A.Literal(line=t.line, value=t.value)
        if t.type == "KEYWORD" and t.value in ("true", "false", "none"):
            self.advance()
            return A.Literal(line=t.line, value={"true": True, "false": False, "none": None}[t.value])
        if t.type == "NAME":
            self.advance()
            return A.Name(line=t.line, ident=t.value)
        if t.type == "OP" and t.value == "(":
            self.advance()
            node = self.expression()
            self.expect("OP", ")", "')'")
            return node
        if t.type == "OP" and t.value == "[":
            self.advance()
            elements = []
            if not self.check("OP", "]"):
                elements.append(self.expression())
                while self.match("OP", ","):
                    if self.check("OP", "]"):
                        break
                    elements.append(self.expression())
            self.expect("OP", "]", "']'")
            return A.ListExpr(line=t.line, elements=elements)
        got = "end of input" if t.type == "EOF" else f"{t.value!r}"
        raise AIDLSyntaxError(f"unexpected {got}", t.line, t.col)


def parse(source: str) -> A.Program:
    tokens = Lexer(source).tokenize()
    return Parser(tokens).parse()
