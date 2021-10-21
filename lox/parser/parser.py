from . import expr as e
from . import stmt
from ..handle_errors import parse_error
from ..lexer.token import Token
import typing as t
from ..lexer.token_type import TokenType as tt
from ..errors import ParseError


class Parser:
    def __init__(self, tokens: t.List[Token]):
        self._tokens = tokens
        self._current = 0

    def _match(self, *types: tt) -> bool:
        # If `Token` have any of the given types, it consumes the `Token`
        # token will be an instance of `Token` class
        """
        Returns true if token is of any of the given types. It also consumes the Token
        """
        for type_ in types:
            if self._check(type_):
                self._advance()
                return True
        return False

    def _check(self, type_: tt):
        """
        Returns true if the current token is of the given type
        """
        # Unlike `match` it doesn't consume the token
        if self._is_at_end():
            return False
        return self._peek().type == type_

    def _advance(self):
        if not self._is_at_end():
            self._current += 1
        return self._previous()

    def _previous(self):
        return self._tokens[self._current - 1]

    def _peek(self):
        return self._tokens[self._current]

    def _is_at_end(self):
        return self._peek().type == tt.EOF

    def _equality(self):
        """
        Rule:
        equality ::= comparison ( ( "!=" | "==" ) comparison )* ;
        """
        # NOTE that if parser never encounters equality operator,
        # it would never enter the while loop. In that case this method matches
        # an equality operator or anything of higher precedence
        expr: e.Expr = self._comparison()
        while self._match(tt.BANG_EQUAL, tt.EQUAL_EQUAL):
            operator: Token = self._previous()  # `Token` that was matched
            right: e.Expr = self._comparison()
            expr = e.Binary(expr, operator, right)

        return expr

    def _comparison(self):
        """
        Rule:
        comparison ::= term ( ( ">" | ">=" | "<" | "<=" ) term )* ;
        """
        expr: e.Expr = self._term()
        while self._match(tt.GREATER_EQUAL, tt.GREATER, tt.LESS_EQUAL, tt.LESS):
            operator: Token = self._previous()
            right: e.Expr = self._term()
            expr = e.Binary(left=expr, operator=operator, right=right)
        return expr

    def _term(self):
        expr: e.Expr = self._factor()

        while self._match(tt.MINUS, tt.PLUS):
            operator = self._previous()
            right = self._factor()
            expr = e.Binary(left=expr, right=right, operator=operator)

        return expr

    def _factor(self):
        expr: e.Expr = self._unary()

        while self._match(tt.STAR, tt.SLASH):
            operator = self._previous()
            right = self._unary()
            expr = e.Binary(expr, operator, right)

        return expr

    def _unary(self):
        while self._match(tt.BANG, tt.MINUS):
            operator = self._previous()
            right = self._unary()
            return e.Unary(operator, right)

        return self._primary()

    def _expression(self):
        return self._assignment()

    def _primary(self):
        if self._match(tt.TRUE):
            return e.Literal(True)
        if self._match(tt.FALSE):
            return e.Literal(False)
        if self._match(tt.STRING, tt.NUMBER):
            return e.Literal(self._previous().literal)
        if self._match(tt.NIL):
            return e.Literal(None)
        if self._match(tt.LEFT_BRACE):
            expr = self._expression()
            self._consume(tt.RIGHT_BRACE, "Expected ')' after expression")
            return e.Grouping(expression=expr)
        if self._match(tt.IDENTIFIER):
            return e.Variable(self._previous())
        raise self._error(self._peek(), "Expected expression.")

    def _consume(self, type_: tt, message: str):
        """
        It's similar to match. If the token is of given type it consumes it.
        If there is some other token, it raises an error.
        """
        if self._check(type_):
            self._advance()
            return self._previous()
        raise self._error(self._peek(), message)

    @staticmethod
    def _error(token: Token, message: str) -> ParseError:
        parse_error(token, message)
        return ParseError()

    def _synchronize(self):
        # So that at least the token where we get error get consumed
        # and we don't fall into infinite recursion
        self._advance()

        while not self._is_at_end():
            if self._previous().type == tt.SEMICOLON:
                return

            if self._peek().type in (
                tt.CLASS,
                tt.FUNCTION,
                tt.VAR,
                tt.FOR,
                tt.IF,
                tt.WHILE,
                tt.PRINT,
                tt.RETURN,
            ):
                return

            self._advance()

    def _print_statement(self):
        value = self._expression()
        self._consume(tt.SEMICOLON, "Expected ';' after value")
        return stmt.Print(expression=value)

    def _expression_statement(self):
        value = self._expression()
        self._consume(tt.SEMICOLON, "Expected ';' after expression")
        return stmt.Expression(expression=value)

    def _statement(self):
        if self._match(tt.PRINT):
            return self._print_statement()
        if self._match(tt.LEFT_PAREN):
            return stmt.Block(statements=self._block())
        if self._match(tt.IF):
            return self._if_statement()
        if self._match(tt.WHILE):
            return self._while_statement()
        if self._match(tt.FOR):
            return self._for_statement()
        return self._expression_statement()

    def _while_statement(self):
        self._consume(tt.LEFT_BRACE, "Expect '(' after while")
        condition = self._expression()
        self._consume(tt.RIGHT_BRACE, "Except ')' after condition")
        body = self._statement()
        return stmt.While(condition, body)

    def parse(self) -> t.Optional[t.List[stmt.Stmt]]:
        """
        program := declaration* EOF
        """
        statements = []
        while not self._is_at_end():
            statements.append(self._declaration())

        return statements

    def _declaration(self):
        try:
            if self._match(tt.VAR):
                return self._variable_declaration()
            return self._statement()
        except ParseError:
            self._synchronize()
            return None

    def _variable_declaration(self):
        # We have already consumed `var` keyword
        name = self._consume(tt.IDENTIFIER, "Expected variable name")
        # If no value is supplied, ex `var x;`, it uses `None`
        initializer = None

        if self._match(tt.EQUAL):
            # If EQUAL matches it have already consume `=` operator
            # initializer is the value of the variable here
            initializer = self._expression()

        self._consume(tt.SEMICOLON, "Expected ';' after variable declaration")
        return stmt.Var(name=name, initializer=initializer)

    def _assignment(self) -> e.Expr:
        """
        assignment  :=  IDENTIFIER "=" assignment
                        | equality ;

        """
        expr = self._or()

        if self._match(tt.EQUAL):
            equals = self._previous()  # Equal `=` sign, that `match` consumed
            # Here we don't loop to build up sequence of same operators
            # Since assignment is right associative we instead recursively call
            # itself to parse RHS
            rhs = self._assignment()
            if isinstance(expr, e.Variable):
                return e.Assign(name=expr.name, value=rhs)
            self._error(equals, "Invalid assignment target")
        return expr

    def _or(self):
        expr = self._and()
        while self._match(tt.OR):
            operator = self._previous()
            right = self._and()
            expr = e.Logical(left=expr, operator=operator, right=right)
        return expr

    def _and(self):
        expr = self._equality()

        while self._match(tt.AND):
            operator = self._previous()
            right = self._equality()
            expr = e.Logical(left=expr, operator=operator, right=right)
        return expr

    def _block(self):
        statements: t.List[stmt.Stmt] = []

        while (not self._check(tt.RIGHT_PAREN)) and (not self._is_at_end()):
            statements.append(self._declaration())

        self._consume(tt.RIGHT_PAREN, "Expect '}' after block")

        return statements

    def _if_statement(self):
        self._consume(tt.LEFT_BRACE, "Expected '(' after 'if'")
        condition = self._expression()
        self._consume(tt.RIGHT_BRACE, "Expected ')' after if condition")

        then_branch = self._statement()
        else_branch = None
        # what will happen when we evaluate nested if statement, like this
        # if (first) if (second) whenTrue(); else whenFalse();
        if self._match(tt.ELSE):
            # This makes it so that the else block is the part of the nearest
            # if statement
            # `then_branch = self._statement()` already have consumed the `else`
            # before it returns
            else_branch = self._statement()

        return stmt.If(condition, then_branch, else_branch)

    def _for_statement(self):
        self._consume(tt.LEFT_BRACE, "Expected '(' after for keyword")
        initializer: t.Optional[stmt.Stmt] = None

        if self._match(tt.SEMICOLON):
            initializer = None
        elif self._match(tt.VAR):
            initializer = self._variable_declaration()
        else:
            initializer = self._expression_statement()

        condition: t.Optional[e.Expr] = None

        if not self._match(tt.SEMICOLON):
            condition = self._expression()
        self._consume(tt.SEMICOLON, "Expected ';' after condition")

        increment: t.Optional[e.Expr] = None

        if not self._check(tt.RIGHT_BRACE):
            increment = self._expression()
        self._consume(tt.RIGHT_BRACE, "Expected ';' after for clauses.")

        body = self._statement()
        if increment is not None:
            body = stmt.Block([increment, body])

        if condition is None:
            condition = e.Literal(True)
        body = stmt.While(condition=condition, block=body)

        if initializer is not None:
            body = stmt.Block([initializer, body])

        return body
