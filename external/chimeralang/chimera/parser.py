"""Parser for ChimeraLang.

Consumes a token stream and produces an AST.
"""

from __future__ import annotations

from chimera.ast_nodes import (
    AllowConstraint,
    AssertStmt,
    BinaryOp,
    BoolLiteral,
    CallExpr,
    CompareChain,
    Constraint,
    Declaration,
    EmitStmt,
    Expr,
    ExprStmt,
    FloatLiteral,
    FnDecl,
    ForbiddenConstraint,
    GateDecl,
    GoalDecl,
    Identifier,
    IfExpr,
    IntLiteral,
    ListLiteral,
    MemberExpr,
    MemoryType,
    MustConstraint,
    NamedType,
    Param,
    PrimitiveType,
    ProbabilisticType,
    Program,
    ReasonDecl,
    ReturnStmt,
    Statement,
    StringLiteral,
    TypeExpr,
    UnaryOp,
    ValDecl,
    GenericType,
)
from chimera.tokens import Token, TokenKind


class ParseError(Exception):
    def __init__(self, message: str, token: Token) -> None:
        self.token = token
        loc = f"L{token.span.line}:{token.span.col}"
        super().__init__(f"ParseError at {loc}: {message} (got {token.kind.name} {token.value!r})")


class Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self._tokens = tokens
        self._pos = 0

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def parse(self) -> Program:
        decls: list[Declaration | Statement] = []
        self._skip_newlines()
        while not self._check(TokenKind.EOF):
            decls.append(self._parse_top_level())
            self._skip_newlines()
        return Program(declarations=decls, span=None)

    # ------------------------------------------------------------------
    # Token helpers
    # ------------------------------------------------------------------

    def _current(self) -> Token:
        return self._tokens[self._pos]

    def _peek_kind(self, offset: int = 0) -> TokenKind:
        idx = self._pos + offset
        if idx < len(self._tokens):
            return self._tokens[idx].kind
        return TokenKind.EOF

    def _check(self, kind: TokenKind) -> bool:
        return self._current().kind == kind

    def _match(self, *kinds: TokenKind) -> Token | None:
        if self._current().kind in kinds:
            return self._advance()
        return None

    def _expect(self, kind: TokenKind, msg: str = "") -> Token:
        if self._current().kind == kind:
            return self._advance()
        raise ParseError(msg or f"Expected {kind.name}", self._current())

    def _advance(self) -> Token:
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def _skip_newlines(self) -> None:
        while self._check(TokenKind.NEWLINE):
            self._advance()

    def _expect_line_end(self) -> None:
        if not self._check(TokenKind.NEWLINE) and not self._check(TokenKind.EOF):
            pass  # lenient — don't error on missing newline
        self._skip_newlines()

    # ------------------------------------------------------------------
    # Top-level
    # ------------------------------------------------------------------

    def _parse_top_level(self) -> Declaration | Statement:
        kind = self._current().kind
        if kind == TokenKind.FN:
            return self._parse_fn()
        if kind == TokenKind.GATE:
            return self._parse_gate()
        if kind == TokenKind.GOAL:
            return self._parse_goal()
        if kind == TokenKind.REASON:
            return self._parse_reason()
        if kind == TokenKind.VAL:
            return self._parse_val()
        return self._parse_statement()

    # ------------------------------------------------------------------
    # Function declaration
    # ------------------------------------------------------------------

    def _parse_fn(self) -> FnDecl:
        span = self._expect(TokenKind.FN).span
        name = self._expect(TokenKind.IDENT, "Expected function name").value
        self._expect(TokenKind.LPAREN, "Expected '(' after function name")
        params = self._parse_param_list()
        self._expect(TokenKind.RPAREN, "Expected ')' after parameters")

        ret_type: TypeExpr | None = None
        if self._match(TokenKind.ARROW):
            ret_type = self._parse_type()

        self._expect_line_end()

        constraints: list[Constraint] = []
        body: list[Statement] = []
        while not self._check(TokenKind.END) and not self._check(TokenKind.EOF):
            self._skip_newlines()
            if self._check(TokenKind.END):
                break
            c = self._try_parse_constraint()
            if c is not None:
                constraints.append(c)
            else:
                body.append(self._parse_statement())
            self._skip_newlines()

        self._expect(TokenKind.END, "Expected 'end' to close function")
        self._expect_line_end()
        return FnDecl(name=name, params=params, return_type=ret_type,
                       constraints=constraints, body=body, span=span)

    # ------------------------------------------------------------------
    # Gate declaration
    # ------------------------------------------------------------------

    def _parse_gate(self) -> GateDecl:
        span = self._expect(TokenKind.GATE).span
        name = self._expect(TokenKind.IDENT, "Expected gate name").value
        self._expect(TokenKind.LPAREN, "Expected '(' after gate name")
        params = self._parse_param_list()
        self._expect(TokenKind.RPAREN, "Expected ')' after parameters")

        ret_type: TypeExpr | None = None
        if self._match(TokenKind.ARROW):
            ret_type = self._parse_type()

        self._expect_line_end()

        branches = 3
        collapse = "majority"
        threshold = 0.85
        fallback = "escalate"
        body: list[Statement] = []

        while not self._check(TokenKind.END) and not self._check(TokenKind.EOF):
            self._skip_newlines()
            if self._check(TokenKind.END):
                break
            if self._check(TokenKind.BRANCHES):
                self._advance()
                self._expect(TokenKind.COLON, "Expected ':' after 'branches'")
                branches = int(self._expect(TokenKind.INT_LIT, "Expected integer").value)
                self._expect_line_end()
            elif self._check(TokenKind.COLLAPSE):
                self._advance()
                self._expect(TokenKind.COLON, "Expected ':' after 'collapse'")
                collapse = self._advance().value
                self._expect_line_end()
            elif self._check(TokenKind.THRESHOLD):
                self._advance()
                self._expect(TokenKind.COLON, "Expected ':' after 'threshold'")
                tok = self._advance()
                threshold = float(tok.value)
                self._expect_line_end()
            elif self._check(TokenKind.FALLBACK):
                self._advance()
                self._expect(TokenKind.COLON, "Expected ':' after 'fallback'")
                fallback = self._advance().value
                self._expect_line_end()
            else:
                body.append(self._parse_statement())
                self._skip_newlines()

        self._expect(TokenKind.END, "Expected 'end' to close gate")
        self._expect_line_end()
        return GateDecl(name=name, params=params, return_type=ret_type,
                         branches=branches, collapse=collapse,
                         threshold=threshold, fallback=fallback,
                         body=body, span=span)

    # ------------------------------------------------------------------
    # Goal declaration
    # ------------------------------------------------------------------

    def _parse_goal(self) -> GoalDecl:
        span = self._expect(TokenKind.GOAL).span
        desc = self._expect(TokenKind.STRING_LIT, "Expected goal description string").value
        self._expect_line_end()

        constraint_list: list[str] = []
        quality_axes: list[str] = []
        explore_budget = 1.0
        body: list[Statement] = []

        while not self._check(TokenKind.END) and not self._check(TokenKind.EOF):
            self._skip_newlines()
            if self._check(TokenKind.END):
                break
            if self._check(TokenKind.CONSTRAINTS):
                self._advance()
                self._expect(TokenKind.COLON)
                constraint_list = self._parse_string_list_block()
            elif self._check(TokenKind.QUALITY):
                self._advance()
                self._expect(TokenKind.COLON)
                quality_axes = self._parse_string_list_block()
            elif self._check(TokenKind.EXPLORE_BUDGET):
                self._advance()
                self._expect(TokenKind.COLON)
                tok = self._advance()
                explore_budget = float(tok.value)
                self._expect_line_end()
            else:
                body.append(self._parse_statement())
                self._skip_newlines()

        self._expect(TokenKind.END, "Expected 'end' to close goal")
        self._expect_line_end()
        return GoalDecl(description=desc, constraints_list=constraint_list,
                         quality_axes=quality_axes, explore_budget=explore_budget,
                         body=body, span=span)

    # ------------------------------------------------------------------
    # Reason declaration
    # ------------------------------------------------------------------

    def _parse_reason(self) -> ReasonDecl:
        span = self._expect(TokenKind.REASON).span
        self._expect(TokenKind.ABOUT, "Expected 'about' after 'reason'")
        self._expect(TokenKind.LPAREN)
        params = self._parse_param_list()
        self._expect(TokenKind.RPAREN)

        ret_type: TypeExpr | None = None
        if self._match(TokenKind.ARROW):
            ret_type = self._parse_type()

        self._expect_line_end()

        given: list[str] = []
        commit_strategy = "highest_consensus"
        body: list[Statement] = []

        while not self._check(TokenKind.END) and not self._check(TokenKind.EOF):
            self._skip_newlines()
            if self._check(TokenKind.END):
                break
            if self._check(TokenKind.GIVEN):
                self._advance()
                self._expect(TokenKind.COLON)
                given = self._parse_string_list_block()
            elif self._check(TokenKind.COMMIT):
                self._advance()
                self._expect(TokenKind.COLON)
                commit_strategy = self._advance().value
                self._expect_line_end()
            else:
                body.append(self._parse_statement())
                self._skip_newlines()

        self._expect(TokenKind.END, "Expected 'end' to close reason block")
        self._expect_line_end()
        return ReasonDecl(name="about", params=params, return_type=ret_type,
                           given=given, commit_strategy=commit_strategy,
                           body=body, span=span)

    # ------------------------------------------------------------------
    # Val declaration
    # ------------------------------------------------------------------

    def _parse_val(self) -> ValDecl:
        self._expect(TokenKind.VAL)
        name = self._expect(TokenKind.IDENT, "Expected variable name").value
        type_ann: TypeExpr | None = None
        if self._match(TokenKind.COLON):
            type_ann = self._parse_type()
        value: Expr | None = None
        if self._match(TokenKind.ASSIGN):
            value = self._parse_expr()
        self._expect_line_end()
        return ValDecl(name=name, type_ann=type_ann, value=value)

    # ------------------------------------------------------------------
    # Statements
    # ------------------------------------------------------------------

    def _parse_statement(self) -> Statement:
        if self._check(TokenKind.VAL):
            return self._parse_val()
        if self._check(TokenKind.RETURN):
            return self._parse_return()
        if self._check(TokenKind.ASSERT):
            return self._parse_assert()
        if self._check(TokenKind.EMIT):
            return self._parse_emit()
        if self._check(TokenKind.IF):
            return ExprStmt(expr=self._parse_if_expr())
        expr = self._parse_expr()
        self._expect_line_end()
        return ExprStmt(expr=expr)

    def _parse_return(self) -> ReturnStmt:
        self._expect(TokenKind.RETURN)
        value: Expr | None = None
        if not self._check(TokenKind.NEWLINE) and not self._check(TokenKind.EOF) and not self._check(TokenKind.END):
            value = self._parse_expr()
        self._expect_line_end()
        return ReturnStmt(value=value)

    def _parse_assert(self) -> AssertStmt:
        self._expect(TokenKind.ASSERT)
        cond = self._parse_expr()
        self._expect_line_end()
        return AssertStmt(condition=cond)

    def _parse_emit(self) -> EmitStmt:
        self._expect(TokenKind.EMIT)
        value = self._parse_expr()
        self._expect_line_end()
        return EmitStmt(value=value)

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------

    def _try_parse_constraint(self) -> Constraint | None:
        if self._check(TokenKind.MUST):
            self._advance()
            self._expect(TokenKind.COLON)
            self._skip_newlines()
            expr = self._parse_expr()
            self._expect_line_end()
            return MustConstraint(expr=expr)
        if self._check(TokenKind.ALLOW):
            self._advance()
            self._expect(TokenKind.COLON)
            caps = self._parse_string_list_block()
            return AllowConstraint(capabilities=caps)
        if self._check(TokenKind.FORBIDDEN):
            self._advance()
            self._expect(TokenKind.COLON)
            caps = self._parse_string_list_block()
            return ForbiddenConstraint(capabilities=caps)
        return None

    def _parse_string_list_block(self) -> list[str]:
        """Parse one or more string literals, each on its own line."""
        self._skip_newlines()
        items: list[str] = []
        while self._check(TokenKind.STRING_LIT):
            items.append(self._advance().value)
            self._skip_newlines()
        return items

    # ------------------------------------------------------------------
    # Expressions — precedence climbing
    # ------------------------------------------------------------------

    def _parse_expr(self) -> Expr:
        return self._parse_or()

    def _parse_or(self) -> Expr:
        left = self._parse_and()
        while self._match(TokenKind.OR):
            right = self._parse_and()
            left = BinaryOp(op="or", left=left, right=right)
        return left

    def _parse_and(self) -> Expr:
        left = self._parse_equality()
        while self._match(TokenKind.AND):
            right = self._parse_equality()
            left = BinaryOp(op="and", left=left, right=right)
        return left

    def _parse_equality(self) -> Expr:
        left = self._parse_comparison()
        while True:
            if self._match(TokenKind.EQ):
                left = BinaryOp(op="==", left=left, right=self._parse_comparison())
            elif self._match(TokenKind.NEQ):
                left = BinaryOp(op="!=", left=left, right=self._parse_comparison())
            else:
                break
        return left

    def _parse_comparison(self) -> Expr:
        left = self._parse_addition()
        while True:
            if self._match(TokenKind.LT):
                left = BinaryOp(op="<", left=left, right=self._parse_addition())
            elif self._match(TokenKind.GT):
                left = BinaryOp(op=">", left=left, right=self._parse_addition())
            elif self._match(TokenKind.LTE):
                left = BinaryOp(op="<=", left=left, right=self._parse_addition())
            elif self._match(TokenKind.GTE):
                left = BinaryOp(op=">=", left=left, right=self._parse_addition())
            else:
                break
        return left

    def _parse_addition(self) -> Expr:
        left = self._parse_multiplication()
        while True:
            if self._match(TokenKind.PLUS):
                left = BinaryOp(op="+", left=left, right=self._parse_multiplication())
            elif self._match(TokenKind.MINUS):
                left = BinaryOp(op="-", left=left, right=self._parse_multiplication())
            else:
                break
        return left

    def _parse_multiplication(self) -> Expr:
        left = self._parse_unary()
        while True:
            if self._match(TokenKind.STAR):
                left = BinaryOp(op="*", left=left, right=self._parse_unary())
            elif self._match(TokenKind.SLASH):
                left = BinaryOp(op="/", left=left, right=self._parse_unary())
            elif self._match(TokenKind.PERCENT):
                left = BinaryOp(op="%", left=left, right=self._parse_unary())
            else:
                break
        return left

    def _parse_unary(self) -> Expr:
        if self._match(TokenKind.MINUS):
            return UnaryOp(op="-", operand=self._parse_unary())
        if self._match(TokenKind.NOT):
            return UnaryOp(op="not", operand=self._parse_unary())
        return self._parse_call()

    def _parse_call(self) -> Expr:
        expr = self._parse_primary()
        while True:
            if self._match(TokenKind.LPAREN):
                args: list[Expr] = []
                if not self._check(TokenKind.RPAREN):
                    args.append(self._parse_expr())
                    while self._match(TokenKind.COMMA):
                        args.append(self._parse_expr())
                self._expect(TokenKind.RPAREN, "Expected ')' after arguments")
                expr = CallExpr(callee=expr, args=args)
            elif self._match(TokenKind.DOT):
                member = self._expect(TokenKind.IDENT, "Expected member name").value
                expr = MemberExpr(obj=expr, member=member)
            else:
                break
        return expr

    def _parse_primary(self) -> Expr:
        tok = self._current()

        if tok.kind == TokenKind.INT_LIT:
            self._advance()
            return IntLiteral(value=int(tok.value))

        if tok.kind == TokenKind.FLOAT_LIT:
            self._advance()
            return FloatLiteral(value=float(tok.value))

        if tok.kind == TokenKind.STRING_LIT:
            self._advance()
            return StringLiteral(value=tok.value)

        if tok.kind == TokenKind.BOOL_LIT:
            self._advance()
            return BoolLiteral(value=tok.value == "true")

        if tok.kind == TokenKind.IDENT:
            self._advance()
            return Identifier(name=tok.value)

        if tok.kind == TokenKind.LBRACKET:
            return self._parse_list_literal()

        if tok.kind == TokenKind.LPAREN:
            self._advance()
            expr = self._parse_expr()
            self._expect(TokenKind.RPAREN, "Expected ')'")
            return expr

        if tok.kind == TokenKind.IF:
            return self._parse_if_expr()

        # Allow type-constructor-like calls: Confident(...), Explore(...)
        if tok.kind in (TokenKind.CONFIDENT, TokenKind.EXPLORE_TYPE, TokenKind.CONVERGE,
                        TokenKind.PROVISIONAL, TokenKind.EPHEMERAL, TokenKind.PERSISTENT,
                        TokenKind.ABOUT):
            self._advance()
            return Identifier(name=tok.value)

        raise ParseError(f"Unexpected token in expression", tok)

    def _parse_if_expr(self) -> IfExpr:
        self._expect(TokenKind.IF)
        cond = self._parse_expr()
        self._expect_line_end()
        then_body: list[Statement] = []
        while not self._check(TokenKind.ELSE) and not self._check(TokenKind.END) and not self._check(TokenKind.EOF):
            self._skip_newlines()
            if self._check(TokenKind.ELSE) or self._check(TokenKind.END):
                break
            then_body.append(self._parse_statement())
        else_body: list[Statement] | None = None
        if self._match(TokenKind.ELSE):
            self._expect_line_end()
            else_body = []
            while not self._check(TokenKind.END) and not self._check(TokenKind.EOF):
                self._skip_newlines()
                if self._check(TokenKind.END):
                    break
                else_body.append(self._parse_statement())
        self._expect(TokenKind.END, "Expected 'end' to close if")
        self._expect_line_end()
        return IfExpr(condition=cond, then_body=then_body, else_body=else_body)

    def _parse_list_literal(self) -> ListLiteral:
        self._expect(TokenKind.LBRACKET)
        elements: list[Expr] = []
        if not self._check(TokenKind.RBRACKET):
            elements.append(self._parse_expr())
            while self._match(TokenKind.COMMA):
                elements.append(self._parse_expr())
        self._expect(TokenKind.RBRACKET, "Expected ']'")
        return ListLiteral(elements=elements)

    # ------------------------------------------------------------------
    # Types
    # ------------------------------------------------------------------

    _PROB_TYPES = {TokenKind.CONFIDENT, TokenKind.EXPLORE_TYPE, TokenKind.CONVERGE, TokenKind.PROVISIONAL}
    _MEM_TYPES = {TokenKind.EPHEMERAL, TokenKind.PERSISTENT}
    _PRIM_TYPES = {TokenKind.INT_TYPE, TokenKind.FLOAT_TYPE, TokenKind.BOOL_TYPE,
                   TokenKind.TEXT_TYPE, TokenKind.VOID_TYPE}
    _GENERIC_TYPES = {TokenKind.LIST_TYPE, TokenKind.MAP_TYPE, TokenKind.OPTION_TYPE, TokenKind.RESULT_TYPE}

    def _parse_type(self) -> TypeExpr:
        tok = self._current()

        if tok.kind in self._PROB_TYPES:
            wrapper = self._advance().value
            self._expect(TokenKind.LT, f"Expected '<' after {wrapper}")
            inner = self._parse_type()
            self._expect(TokenKind.GT, f"Expected '>' to close {wrapper}<...>")
            return ProbabilisticType(wrapper=wrapper, inner=inner)

        if tok.kind in self._MEM_TYPES:
            scope = self._advance().value
            self._expect(TokenKind.LT, f"Expected '<' after {scope}")
            inner = self._parse_type()
            self._expect(TokenKind.GT, f"Expected '>' to close {scope}<...>")
            return MemoryType(scope=scope, inner=inner)

        if tok.kind in self._PRIM_TYPES:
            self._advance()
            return PrimitiveType(name=tok.value)

        if tok.kind in self._GENERIC_TYPES:
            name = self._advance().value
            self._expect(TokenKind.LT, f"Expected '<' after {name}")
            params: list[TypeExpr] = [self._parse_type()]
            while self._match(TokenKind.COMMA):
                params.append(self._parse_type())
            self._expect(TokenKind.GT, f"Expected '>' to close {name}<...>")
            return GenericType(name=name, params=params)

        if tok.kind == TokenKind.IDENT:
            self._advance()
            return NamedType(name=tok.value)

        raise ParseError("Expected type expression", tok)

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def _parse_param_list(self) -> list[Param]:
        params: list[Param] = []
        if self._check(TokenKind.RPAREN):
            return params
        params.append(self._parse_param())
        while self._match(TokenKind.COMMA):
            params.append(self._parse_param())
        return params

    def _parse_param(self) -> Param:
        name = self._expect(TokenKind.IDENT, "Expected parameter name").value
        self._expect(TokenKind.COLON, "Expected ':' after parameter name")
        type_ann = self._parse_type()
        return Param(name=name, type_ann=type_ann)

    def _parse_ident_list_bracket(self) -> list[str]:
        self._expect(TokenKind.LBRACKET, "Expected '['")
        items: list[str] = []
        if not self._check(TokenKind.RBRACKET):
            items.append(self._advance().value)
            while self._match(TokenKind.COMMA):
                items.append(self._advance().value)
        self._expect(TokenKind.RBRACKET, "Expected ']'")
        return items

    def _parse_ident_list_comma(self) -> list[str]:
        items: list[str] = [self._advance().value]
        while self._match(TokenKind.COMMA):
            items.append(self._advance().value)
        return items

    def _parse_quality_chain(self) -> list[str]:
        items: list[str] = [self._advance().value]
        while self._match(TokenKind.GT):
            items.append(self._advance().value)
        return items
