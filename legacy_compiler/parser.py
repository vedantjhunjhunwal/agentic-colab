"""
============================================================
  DSL Compiler – Phase 2: PARSER
  Recursive-Descent Parser → builds an AST
  Implements full error recovery (panic-mode / sync sets)
============================================================
"""

from typing import List, Optional, Set
from lexer      import Token, TokenType, RESERVED_WORDS
from ast_nodes  import *


# ──────────────────────────────────────────────────────────
#  Parse Error
# ──────────────────────────────────────────────────────────
class ParseError(Exception):
    def __init__(self, message: str, line: int, col: int):
        super().__init__(message)
        self.message = message
        self.line    = line
        self.col     = col

    def __str__(self):
        return f"[PARSE ERROR] Line {self.line}, Col {self.col}: {self.message}"


# ──────────────────────────────────────────────────────────
#  Parser
# ──────────────────────────────────────────────────────────
class Parser:
    def __init__(self, tokens: List[Token]):
        self.tokens  : List[Token]      = tokens
        self.pos     : int              = 0
        self.errors  : List[ParseError] = []

    # ── Token navigation ──────────────────────────────────
    def _current(self) -> Token:
        return self.tokens[self.pos]

    def _peek(self, offset: int = 1) -> Token:
        idx = self.pos + offset
        if idx < len(self.tokens):
            return self.tokens[idx]
        return self.tokens[-1]   # EOF

    def _is(self, *args) -> bool:
        tok = self._current()
        for arg in args:
            if isinstance(arg, TokenType):
                if tok.type == arg:
                    return True
            elif isinstance(arg, str):
                if tok.type == TokenType.RESERVED_WORD and tok.value == arg:
                    return True
                if tok.type == TokenType.IDENTIFIER and tok.value == arg:
                    return True
        return False

    def _consume(self, *args, required: bool = True) -> Optional[Token]:
        """Consume current token if it matches; otherwise report error."""
        tok = self._current()
        if self._is(*args):
            self.pos += 1
            return tok
        if required:
            expected = ', '.join(str(a.name if isinstance(a, TokenType) else a) for a in args)
            err = ParseError(
                f"Expected {expected}, got {tok.type.name}={tok.value!r}",
                tok.line, tok.column
            )
            self.errors.append(err)
        return None

    def _sync(self, follow_set: Set):
        """Panic-mode error recovery: skip until a token in follow_set."""
        while not self._is(TokenType.EOF) and not self._is(*follow_set):
            self.pos += 1

    # ── Entry point ───────────────────────────────────────
    def parse(self) -> Optional[ProgramNode]:
        try:
            node = self._parse_program()
            return node
        except Exception as e:
            self.errors.append(ParseError(str(e), 0, 0))
            return None

    # ──────────────────────────────────────────────────────
    #  Grammar productions
    # ──────────────────────────────────────────────────────

    # program -> 'program' id ';' var_declarations subprogram_decls compound '.'
    def _parse_program(self) -> ProgramNode:
        tok = self._current()
        node = ProgramNode(line=tok.line, col=tok.column)
        self._consume('program')
        id_tok = self._consume(TokenType.IDENTIFIER)
        node.name = id_tok.value if id_tok else "<unknown>"
        self._consume(TokenType.SEMICOLON)
        node.var_decls   = self._parse_var_declarations()
        node.subprograms = self._parse_subprogram_declarations()
        node.body        = self._parse_compound_statement()
        self._consume(TokenType.DOT)
        return node

    # var_declarations -> 'var' (identifier_list ':' type ';')+ | ε
    def _parse_var_declarations(self) -> List[VarDeclNode]:
        decls = []
        if not self._is('var'):
            return decls
        self._consume('var')
        while self._is(TokenType.IDENTIFIER):
            decl = self._parse_one_var_decl()
            if decl:
                decls.append(decl)
        return decls

    def _parse_one_var_decl(self) -> Optional[VarDeclNode]:
        tok  = self._current()
        node = VarDeclNode(line=tok.line, col=tok.column)
        node.names = self._parse_identifier_list()
        self._consume(TokenType.COLON)
        node.var_type = self._parse_type()
        self._consume(TokenType.SEMICOLON)
        return node

    # identifier_list -> id (',' id)*
    def _parse_identifier_list(self) -> List[str]:
        names = []
        tok = self._consume(TokenType.IDENTIFIER)
        if tok:
            names.append(tok.value)
        while self._is(TokenType.COMMA):
            self._consume(TokenType.COMMA)
            tok = self._consume(TokenType.IDENTIFIER)
            if tok:
                names.append(tok.value)
        return names

    # type -> standard_type | 'array' '[' num '..' num ']' 'of' standard_type
    def _parse_type(self) -> TypeNode:
        tok  = self._current()
        node = TypeNode(line=tok.line, col=tok.column)
        if self._is('array'):
            self._consume('array')
            self._consume(TokenType.LBRACKET)
            low_tok = self._consume(TokenType.INTEGER_LITERAL)
            self._consume(TokenType.DOTDOT)
            high_tok = self._consume(TokenType.INTEGER_LITERAL)
            self._consume(TokenType.RBRACKET)
            self._consume('of')
            std = self._parse_standard_type()
            node.type_name = f"array[{low_tok.value if low_tok else '?'}..{high_tok.value if high_tok else '?'}] of {std}"
            node.low  = int(low_tok.value)  if low_tok  else 0
            node.high = int(high_tok.value) if high_tok else 0
        else:
            node.type_name = self._parse_standard_type()
        return node

    def _parse_standard_type(self) -> str:
        tok = self._consume('integer')
        return 'integer' if tok else 'unknown'

    # subprogram_declarations -> (subprogram_declaration ';')*
    def _parse_subprogram_declarations(self) -> List[SubprogramNode]:
        subs = []
        while self._is('function') or self._is('procedure'):
            sub = self._parse_subprogram()
            if sub:
                subs.append(sub)
                self._consume(TokenType.SEMICOLON)
        return subs

    # subprogram_declaration -> subprogram_head var_declarations compound
    def _parse_subprogram(self) -> SubprogramNode:
        tok  = self._current()
        node = SubprogramNode(line=tok.line, col=tok.column)
        if self._is('function'):
            self._consume('function')
            node.kind = 'function'
        else:
            self._consume('procedure')
            node.kind = 'procedure'
        id_tok = self._consume(TokenType.IDENTIFIER)
        node.name = id_tok.value if id_tok else "<unknown>"
        # arguments
        if self._is(TokenType.LPAREN):
            node.params = self._parse_arguments()
        # return type for function
        if node.kind == 'function':
            self._consume(TokenType.COLON)
            node.return_type = self._parse_standard_type()
        self._consume(TokenType.SEMICOLON)
        node.var_decls = self._parse_var_declarations()
        node.body      = self._parse_compound_statement()
        return node

    # arguments -> '(' parameter_list ')' | ε
    def _parse_arguments(self) -> List[VarDeclNode]:
        self._consume(TokenType.LPAREN)
        params = []
        if not self._is(TokenType.RPAREN):
            params = self._parse_parameter_list()
        self._consume(TokenType.RPAREN)
        return params

    # parameter_list -> (identifier_list ':' type (';' identifier_list ':' type)*
    def _parse_parameter_list(self) -> List[VarDeclNode]:
        params = []
        decl = self._parse_one_param_decl()
        if decl:
            params.append(decl)
        while self._is(TokenType.SEMICOLON):
            self._consume(TokenType.SEMICOLON)
            decl = self._parse_one_param_decl()
            if decl:
                params.append(decl)
        return params

    def _parse_one_param_decl(self) -> Optional[VarDeclNode]:
        tok  = self._current()
        node = VarDeclNode(line=tok.line, col=tok.column)
        node.names    = self._parse_identifier_list()
        self._consume(TokenType.COLON)
        node.var_type = self._parse_type()
        return node

    # compound_statement -> 'begin' statement_list 'end'
    def _parse_compound_statement(self) -> CompoundStmt:
        tok  = self._current()
        node = CompoundStmt(line=tok.line, col=tok.column)
        self._consume('begin')
        node.statements = self._parse_statement_list()
        self._consume('end')
        return node

    # statement_list -> statement (';' statement)*
    def _parse_statement_list(self) -> List[ASTNode]:
        stmts = []
        stmt = self._parse_statement()
        if stmt:
            stmts.append(stmt)
        while self._is(TokenType.SEMICOLON):
            self._consume(TokenType.SEMICOLON)
            # Don't consume if next is 'end' (trailing semicolon ok)
            if self._is('end'):
                break
            stmt = self._parse_statement()
            if stmt:
                stmts.append(stmt)
        return stmts

    # statement -> assignment | proc_call | compound | if | while | read | write | ε
    def _parse_statement(self) -> Optional[ASTNode]:
        tok = self._current()

        if self._is('begin'):
            return self._parse_compound_statement()

        if self._is('if'):
            return self._parse_if_statement()

        if self._is('while'):
            return self._parse_while_statement()

        if self._is('read'):
            return self._parse_read_statement()

        if self._is('write'):
            return self._parse_write_statement()

        if self._is(TokenType.IDENTIFIER):
            # Disambiguate: assignment vs procedure call
            # Look ahead: id ':=' ... → assignment
            #             id '(' ... → procedure call
            #             id ';'/'end' → procedure call no args
            nxt = self._peek()
            if nxt.type == TokenType.ASSIGN or \
               (nxt.type == TokenType.LBRACKET):
                return self._parse_assignment()
            else:
                return self._parse_procedure_call()

        # ε (empty statement)
        return None

    # assignment -> variable ':=' expression
    def _parse_assignment(self) -> AssignStmt:
        tok  = self._current()
        node = AssignStmt(line=tok.line, col=tok.column)
        node.variable = self._parse_variable()
        self._consume(TokenType.ASSIGN)
        node.value = self._parse_expression()
        return node

    # variable -> id ('[' expression ']')?
    def _parse_variable(self) -> VariableExpr:
        tok  = self._current()
        node = VariableExpr(line=tok.line, col=tok.column)
        id_tok = self._consume(TokenType.IDENTIFIER)
        node.name = id_tok.value if id_tok else "<unknown>"
        if self._is(TokenType.LBRACKET):
            self._consume(TokenType.LBRACKET)
            node.index = self._parse_expression()
            self._consume(TokenType.RBRACKET)
        return node

    # procedure_statement -> id | id '(' expression_list ')'
    def _parse_procedure_call(self) -> ProcCallStmt:
        tok  = self._current()
        node = ProcCallStmt(line=tok.line, col=tok.column)
        id_tok = self._consume(TokenType.IDENTIFIER)
        node.name = id_tok.value if id_tok else "<unknown>"
        if self._is(TokenType.LPAREN):
            self._consume(TokenType.LPAREN)
            if not self._is(TokenType.RPAREN):
                node.arguments = self._parse_expression_list()
            self._consume(TokenType.RPAREN)
        return node

    # if expression then statement (else statement)?
    def _parse_if_statement(self) -> IfStmt:
        tok  = self._current()
        node = IfStmt(line=tok.line, col=tok.column)
        self._consume('if')
        node.condition = self._parse_expression()
        self._consume('then')
        node.then_stmt = self._parse_statement()
        if self._is('else'):
            self._consume('else')
            node.else_stmt = self._parse_statement()
        return node

    # while expression do statement
    def _parse_while_statement(self) -> WhileStmt:
        tok  = self._current()
        node = WhileStmt(line=tok.line, col=tok.column)
        self._consume('while')
        node.condition = self._parse_expression()
        self._consume('do')
        node.body = self._parse_statement()
        return node

    # read ( identifier_list )
    def _parse_read_statement(self) -> ReadStmt:
        tok  = self._current()
        node = ReadStmt(line=tok.line, col=tok.column)
        self._consume('read')
        self._consume(TokenType.LPAREN)
        # parse variable list
        var_node = self._parse_variable()
        node.variables.append(var_node)
        while self._is(TokenType.COMMA):
            self._consume(TokenType.COMMA)
            node.variables.append(self._parse_variable())
        self._consume(TokenType.RPAREN)
        return node

    # write ( outputlist )
    def _parse_write_statement(self) -> WriteStmt:
        tok  = self._current()
        node = WriteStmt(line=tok.line, col=tok.column)
        self._consume('write')
        self._consume(TokenType.LPAREN)
        node.items = self._parse_output_list()
        self._consume(TokenType.RPAREN)
        return node

    def _parse_output_list(self) -> List[ASTNode]:
        items = [self._parse_output_item()]
        while self._is(TokenType.COMMA):
            self._consume(TokenType.COMMA)
            items.append(self._parse_output_item())
        return items

    def _parse_output_item(self) -> ASTNode:
        if self._is(TokenType.STRING_LITERAL):
            tok = self._advance_token()
            return StringLiteral(value=tok.value, line=tok.line, col=tok.column)
        return self._parse_expression()

    def _advance_token(self) -> Token:
        tok = self._current()
        self.pos += 1
        return tok

    # expression_list -> expression (',' expression)*
    def _parse_expression_list(self) -> List[ASTNode]:
        exprs = [self._parse_expression()]
        while self._is(TokenType.COMMA):
            self._consume(TokenType.COMMA)
            exprs.append(self._parse_expression())
        return exprs

    # expression -> simple_expression (relop simple_expression)?
    RELOPS = {TokenType.EQUALS, TokenType.NEQ, TokenType.LT,
              TokenType.LEQ,    TokenType.GT,  TokenType.GEQ}

    def _parse_expression(self) -> ASTNode:
        left = self._parse_simple_expression()
        tok  = self._current()
        if tok.type in self.RELOPS:
            op = tok.value
            self.pos += 1
            right = self._parse_simple_expression()
            return BinaryExpr(op=op, left=left, right=right, line=tok.line, col=tok.column)
        return left

    # simple_expression -> ('+' | '-')? term (('+' | '-' | 'or') term)*
    def _parse_simple_expression(self) -> ASTNode:
        unary_op = None
        tok      = self._current()
        if self._is(TokenType.PLUS) or self._is(TokenType.MINUS):
            unary_op = tok.value
            self.pos += 1
        node = self._parse_term()
        if unary_op == '-':
            node = UnaryExpr(op='-', operand=node, line=tok.line, col=tok.column)
        while self._is(TokenType.PLUS) or self._is(TokenType.MINUS) or self._is('or'):
            op_tok = self._current()
            self.pos += 1
            right  = self._parse_term()
            node   = BinaryExpr(op=op_tok.value, left=node, right=right,
                                 line=op_tok.line, col=op_tok.column)
        return node

    # term -> factor (('*' | '/' | 'and') factor)*
    def _parse_term(self) -> ASTNode:
        node = self._parse_factor()
        while self._is(TokenType.STAR) or self._is(TokenType.SLASH) or self._is('and'):
            op_tok = self._current()
            self.pos += 1
            right  = self._parse_factor()
            node   = BinaryExpr(op=op_tok.value, left=node, right=right,
                                 line=op_tok.line, col=op_tok.column)
        return node

    # factor -> id | id '[' expr ']' | id '(' expr_list ')' | num | '(' expr ')' | 'not' factor
    def _parse_factor(self) -> ASTNode:
        tok = self._current()

        if self._is('not'):
            self.pos += 1
            operand = self._parse_factor()
            return UnaryExpr(op='not', operand=operand, line=tok.line, col=tok.column)

        if self._is(TokenType.LPAREN):
            self.pos += 1
            expr = self._parse_expression()
            self._consume(TokenType.RPAREN)
            return expr

        if self._is(TokenType.INTEGER_LITERAL):
            self.pos += 1
            return IntegerLiteral(value=int(tok.value), line=tok.line, col=tok.column)

        if self._is(TokenType.STRING_LITERAL):
            self.pos += 1
            return StringLiteral(value=tok.value, line=tok.line, col=tok.column)

        if self._is(TokenType.IDENTIFIER):
            self.pos += 1
            nxt = self._current()
            if nxt.type == TokenType.LBRACKET:
                self.pos += 1
                idx_expr = self._parse_expression()
                self._consume(TokenType.RBRACKET)
                return VariableExpr(name=tok.value, index=idx_expr,
                                    line=tok.line, col=tok.column)
            if nxt.type == TokenType.LPAREN:
                self.pos += 1
                args = []
                if not self._is(TokenType.RPAREN):
                    args = self._parse_expression_list()
                self._consume(TokenType.RPAREN)
                return FuncCallExpr(name=tok.value, arguments=args,
                                    line=tok.line, col=tok.column)
            return VariableExpr(name=tok.value, line=tok.line, col=tok.column)

        # Error recovery
        err = ParseError(
            f"Unexpected token {tok.type.name}={tok.value!r} in expression",
            tok.line, tok.column
        )
        self.errors.append(err)
        self.pos += 1
        return IntegerLiteral(value=0, line=tok.line, col=tok.column)
