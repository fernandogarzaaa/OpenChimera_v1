"""Lexer (tokenizer) for ChimeraLang.

Converts raw source text into a stream of tokens.
"""

from __future__ import annotations

from chimera.tokens import KEYWORDS, SourceSpan, Token, TokenKind


class LexError(Exception):
    def __init__(self, message: str, line: int, col: int) -> None:
        self.line = line
        self.col = col
        super().__init__(f"LexError at L{line}:{col}: {message}")


class Lexer:
    def __init__(self, source: str, filename: str = "<stdin>") -> None:
        self._src = source
        self._file = filename
        self._pos = 0
        self._line = 1
        self._col = 1
        self._tokens: list[Token] = []

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def tokenize(self) -> list[Token]:
        while not self._at_end():
            self._skip_whitespace_and_comments()
            if self._at_end():
                break
            ch = self._peek()

            if ch == "\n":
                self._emit_single(TokenKind.NEWLINE, "\n")
                self._advance()
                self._line += 1
                self._col = 1
                continue

            if ch == '"':
                self._read_string()
            elif ch.isdigit():
                self._read_number()
            elif ch.isalpha() or ch == "_":
                self._read_ident_or_keyword()
            else:
                self._read_symbol()

        self._tokens.append(
            Token(TokenKind.EOF, "", self._span(0))
        )
        return self._tokens

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _at_end(self) -> bool:
        return self._pos >= len(self._src)

    def _peek(self, offset: int = 0) -> str:
        idx = self._pos + offset
        return self._src[idx] if idx < len(self._src) else "\0"

    def _advance(self) -> str:
        ch = self._src[self._pos]
        self._pos += 1
        self._col += 1
        return ch

    def _span(self, length: int) -> SourceSpan:
        return SourceSpan(
            line=self._line,
            col=self._col - length,
            offset=self._pos - length,
            length=length,
            file=self._file,
        )

    def _emit(self, kind: TokenKind, value: str, length: int) -> None:
        self._tokens.append(Token(kind, value, self._span(length)))

    def _emit_single(self, kind: TokenKind, value: str) -> None:
        self._tokens.append(
            Token(kind, value, SourceSpan(self._line, self._col, self._pos, len(value), self._file))
        )

    # ------------------------------------------------------------------
    # Skip whitespace / comments
    # ------------------------------------------------------------------

    def _skip_whitespace_and_comments(self) -> None:
        while not self._at_end():
            ch = self._peek()
            if ch in (" ", "\t", "\r"):
                self._advance()
            elif ch == "/" and self._peek(1) == "/":
                # line comment
                while not self._at_end() and self._peek() != "\n":
                    self._advance()
            elif ch == "/" and self._peek(1) == "*":
                # block comment
                self._advance()  # /
                self._advance()  # *
                while not self._at_end():
                    if self._peek() == "*" and self._peek(1) == "/":
                        self._advance()
                        self._advance()
                        break
                    if self._peek() == "\n":
                        self._line += 1
                        self._col = 0
                    self._advance()
            else:
                break

    # ------------------------------------------------------------------
    # Readers
    # ------------------------------------------------------------------

    def _read_string(self) -> None:
        self._advance()  # opening "
        start = self._pos
        while not self._at_end() and self._peek() != '"':
            if self._peek() == "\\":
                self._advance()  # skip escape char
            if self._peek() == "\n":
                self._line += 1
                self._col = 0
            self._advance()
        if self._at_end():
            raise LexError("Unterminated string literal", self._line, self._col)
        value = self._src[start : self._pos]
        self._advance()  # closing "
        self._emit(TokenKind.STRING_LIT, value, len(value) + 2)

    def _read_number(self) -> None:
        start = self._pos
        is_float = False
        while not self._at_end() and (self._peek().isdigit() or self._peek() == "."):
            if self._peek() == ".":
                if is_float:
                    break
                is_float = True
            self._advance()
        text = self._src[start : self._pos]
        kind = TokenKind.FLOAT_LIT if is_float else TokenKind.INT_LIT
        self._emit(kind, text, len(text))

    def _read_ident_or_keyword(self) -> None:
        start = self._pos
        while not self._at_end() and (self._peek().isalnum() or self._peek() == "_"):
            self._advance()
        text = self._src[start : self._pos]
        kind = KEYWORDS.get(text, TokenKind.IDENT)
        self._emit(kind, text, len(text))

    def _read_symbol(self) -> None:
        ch = self._advance()
        two = ch + self._peek() if not self._at_end() else ch

        TWO_CHAR: dict[str, TokenKind] = {
            "->": TokenKind.ARROW,
            "=>": TokenKind.FAT_ARROW,
            "==": TokenKind.EQ,
            "!=": TokenKind.NEQ,
            "<=": TokenKind.LTE,
            ">=": TokenKind.GTE,
        }

        if two in TWO_CHAR:
            self._advance()
            self._emit(TWO_CHAR[two], two, 2)
            return

        ONE_CHAR: dict[str, TokenKind] = {
            "+": TokenKind.PLUS,
            "-": TokenKind.MINUS,
            "*": TokenKind.STAR,
            "/": TokenKind.SLASH,
            "%": TokenKind.PERCENT,
            "<": TokenKind.LT,
            ">": TokenKind.GT,
            "=": TokenKind.ASSIGN,
            "(": TokenKind.LPAREN,
            ")": TokenKind.RPAREN,
            "[": TokenKind.LBRACKET,
            "]": TokenKind.RBRACKET,
            "{": TokenKind.LBRACE,
            "}": TokenKind.RBRACE,
            ",": TokenKind.COMMA,
            ":": TokenKind.COLON,
            ".": TokenKind.DOT,
            "|": TokenKind.PIPE,
        }

        if ch in ONE_CHAR:
            self._emit(ONE_CHAR[ch], ch, 1)
        else:
            raise LexError(f"Unexpected character: {ch!r}", self._line, self._col - 1)
