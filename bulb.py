import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


class CompileError(Exception):
    pass


TOKEN_PATTERN = re.compile(r"\s+|&&|\|\||==|!=|<=|>=|[0-9]+|[A-Za-z_][A-Za-z0-9_]*|[()+*/<>=,!-]|[.\[\]]")
FUNCTION_PATTERN = re.compile(r"fn ([A-Za-z_][A-Za-z0-9_]*)\((.*)\) -> (i64|bool):")
STRUCT_PATTERN = re.compile(r"struct ([A-Za-z_][A-Za-z0-9_]*):")
DECLARATION_PATTERN = re.compile(r"(let|var) ([A-Za-z_][A-Za-z0-9_]*) = (.+)")
ASSIGNMENT_PATTERN = re.compile(r"set ([A-Za-z_][A-Za-z0-9_]*) = (.+)")
PARAMETER_PATTERN = re.compile(r"([A-Za-z_][A-Za-z0-9_]*): (i64|bool)")
FIELD_PATTERN = re.compile(r"([A-Za-z_][A-Za-z0-9_]*): (i64|bool)")
C_TYPES = {"i64": "int64_t", "bool": "_Bool"}


def tokenize(expression, line_number):
    tokens = []
    position = 0
    while position < len(expression):
        match = TOKEN_PATTERN.match(expression, position)
        if match is None:
            raise CompileError(f"line {line_number}: unexpected character {expression[position]!r}")
        value = match.group()
        position = match.end()
        if not value.isspace():
            tokens.append(value)
    return tokens


class ExpressionParser:
    def __init__(self, tokens, line_number):
        self.tokens = tokens
        self.line_number = line_number
        self.position = 0

    def parse(self):
        expression = self.parse_binary(0)
        if self.position != len(self.tokens):
            self.fail(f"unexpected token {self.tokens[self.position]!r}")
        return expression

    def parse_binary(self, minimum_precedence):
        left = self.parse_atom()
        precedence = {"||": 1, "&&": 2, "==": 5, "!=": 5, "<": 5, "<=": 5, ">": 5, ">=": 5, "+": 10, "-": 10, "*": 20, "/": 20}
        while self.position < len(self.tokens):
            operator = self.tokens[self.position]
            operator_precedence = precedence.get(operator, -1)
            if operator_precedence < minimum_precedence:
                break
            self.position += 1
            right = self.parse_binary(operator_precedence + 1)
            left = ("binary", operator, left, right)
        return left

    def parse_atom(self):
        if self.position >= len(self.tokens):
            self.fail("expected an expression")
        token = self.tokens[self.position]
        self.position += 1
        if token.isdecimal():
            return ("integer", token)
        if token in {"true", "false"}:
            return ("boolean", token == "true")
        if token == "-":
            return ("negate", self.parse_atom())
        if token == "!":
            return ("not", self.parse_atom())
        if token == "(":
            expression = self.parse_binary(0)
            if self.position >= len(self.tokens) or self.tokens[self.position] != ")":
                self.fail("expected ')'")
            self.position += 1
            return expression
        if token == "[":
            elements = []
            if self.position < len(self.tokens) and self.tokens[self.position] != "]":
                while True:
                    elements.append(self.parse_binary(0))
                    if self.position >= len(self.tokens) or self.tokens[self.position] != ",":
                        break
                    self.position += 1
            if self.position >= len(self.tokens) or self.tokens[self.position] != "]":
                self.fail("expected ']' after array elements")
            self.position += 1
            return ("array", elements)
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token):
            expression = ("name", token)
            if self.position < len(self.tokens) and self.tokens[self.position] == "(":
                self.position += 1
                arguments = []
                if self.position < len(self.tokens) and self.tokens[self.position] != ")":
                    while True:
                        arguments.append(self.parse_binary(0))
                        if self.position >= len(self.tokens) or self.tokens[self.position] != ",":
                            break
                        self.position += 1
                if self.position >= len(self.tokens) or self.tokens[self.position] != ")":
                    self.fail("expected ')' after function arguments")
                self.position += 1
                expression = ("call", token, arguments)
            while self.position < len(self.tokens):
                if self.tokens[self.position] == "[":
                    self.position += 1
                    index = self.parse_binary(0)
                    if self.position >= len(self.tokens) or self.tokens[self.position] != "]":
                        self.fail("expected ']' after index")
                    self.position += 1
                    expression = ("index", expression, index)
                elif self.tokens[self.position] == ".":
                    self.position += 1
                    if self.position >= len(self.tokens) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.tokens[self.position]):
                        self.fail("expected a field name after '.'")
                    field_name = self.tokens[self.position]
                    self.position += 1
                    expression = ("field", expression, field_name)
                else:
                    break
            return expression
        self.fail(f"expected an integer, name, or '(', got {token!r}")

    def fail(self, message):
        raise CompileError(f"line {self.line_number}: {message}")


def parse_expression(expression, line_number):
    tokens = tokenize(expression, line_number)
    return ExpressionParser(tokens, line_number).parse()


def parse_block(lines, position, indentation, loop_depth=0):
    statements = []
    while position < len(lines):
        line_number, line = lines[position]
        current_indentation = len(line) - len(line.lstrip(" "))
        if line[:current_indentation].find("\t") >= 0 or line[current_indentation:].startswith("\t"):
            raise CompileError(f"line {line_number}: use spaces for indentation")
        if current_indentation < indentation:
            break
        if current_indentation > indentation:
            raise CompileError(f"line {line_number}: unexpected indentation")

        statement = line[indentation:]
        if statement.startswith("if ") and statement.endswith(":"):
            condition = parse_expression(statement[3:-1], line_number)
            true_body, next_position = parse_block(lines, position + 1, indentation + 4, loop_depth)
            if not true_body:
                raise CompileError(f"line {line_number}: if body cannot be empty")
            false_body = []
            if next_position < len(lines):
                else_number, else_line = lines[next_position]
                else_indentation = len(else_line) - len(else_line.lstrip(" "))
                if else_indentation == indentation and else_line[indentation:] == "else:":
                    false_body, next_position = parse_block(lines, next_position + 1, indentation + 4, loop_depth)
                    if not false_body:
                        raise CompileError(f"line {else_number}: else body cannot be empty")
            statements.append(("if", condition, true_body, false_body, line_number))
            position = next_position
            continue

        if statement.startswith("while ") and statement.endswith(":"):
            condition = parse_expression(statement[6:-1], line_number)
            body, next_position = parse_block(lines, position + 1, indentation + 4, loop_depth + 1)
            if not body:
                raise CompileError(f"line {line_number}: while loop body cannot be empty")
            statements.append(("while", condition, body, line_number))
            position = next_position
            continue

        declaration = DECLARATION_PATTERN.fullmatch(statement)
        assignment = ASSIGNMENT_PATTERN.fullmatch(statement)
        if declaration:
            kind, name, expression = declaration.groups()
            statements.append(("declare", name, parse_expression(expression, line_number), line_number, kind == "var"))
        elif assignment:
            name, expression = assignment.groups()
            statements.append(("set", name, parse_expression(expression, line_number), line_number))
        elif statement.startswith("return "):
            if loop_depth:
                raise CompileError(f"line {line_number}: return inside a while loop is not supported yet")
            statements.append(("return", parse_expression(statement[7:], line_number), line_number))
        else:
            raise CompileError(f"line {line_number}: invalid statement")
        position += 1
    return statements, position


def block_returns(statements):
    if not statements:
        return False
    final_statement = statements[-1]
    if final_statement[0] == "return":
        return True
    return (
        final_statement[0] == "if"
        and bool(final_statement[3])
        and block_returns(final_statement[2])
        and block_returns(final_statement[3])
    )


def parse_program(source):
    lines = [(number, line) for number, line in enumerate(source.splitlines(), 1) if line.strip()]
    structs = {}
    functions = []
    names = set()
    position = 0
    while position < len(lines):
        line_number, line = lines[position]
        struct_match = STRUCT_PATTERN.fullmatch(line)
        if struct_match:
            struct_name = struct_match.group(1)
            if struct_name in structs:
                raise CompileError(f"line {line_number}: struct {struct_name!r} is already defined")
            fields = []
            position += 1
            while position < len(lines):
                field_number, field_line = lines[position]
                field_indentation = len(field_line) - len(field_line.lstrip(" "))
                if field_indentation < 4:
                    break
                if field_indentation != 4:
                    raise CompileError(f"line {field_number}: struct fields must be indented by four spaces")
                field_match = FIELD_PATTERN.fullmatch(field_line[4:])
                if field_match is None:
                    raise CompileError(f"line {field_number}: struct fields must have type i64 or bool")
                field_name, field_type = field_match.groups()
                if field_name in [existing_name for existing_name, _ in fields]:
                    raise CompileError(f"line {field_number}: duplicate field {field_name!r}")
                fields.append((field_name, field_type))
                position += 1
            if not fields:
                raise CompileError(f"line {line_number}: struct must declare at least one field")
            structs[struct_name] = fields
            continue

        match = FUNCTION_PATTERN.fullmatch(line)
        if match is None:
            raise CompileError(f"line {line_number}: expected 'fn name(args) -> i64:'")
        name, parameter_text, return_type = match.groups()
        if name in names:
            raise CompileError(f"line {line_number}: function {name!r} is already defined")
        names.add(name)

        parameters = []
        if parameter_text.strip():
            for parameter in parameter_text.split(","):
                parameter_match = PARAMETER_PATTERN.fullmatch(parameter.strip())
                if parameter_match is None:
                    raise CompileError(f"line {line_number}: parameters must have the form 'name: i64' or 'name: bool'")
                parameter_name, parameter_type = parameter_match.groups()
                if parameter_name in [existing_name for existing_name, _ in parameters]:
                    raise CompileError(f"line {line_number}: duplicate parameter {parameter_name!r}")
                parameters.append((parameter_name, parameter_type))

        body, position = parse_block(lines, position + 1, 4)
        if not block_returns(body):
            raise CompileError(f"function {name!r} must return on every path")
        functions.append((name, parameters, return_type, body, line_number))

    signatures = {name: (parameters, return_type) for name, parameters, return_type, _, _ in functions}
    if "main" not in signatures or signatures["main"] != ([], "i64"):
        raise CompileError("program must define 'fn main() -> i64:'")
    if set(structs) & set(signatures):
        raise CompileError("struct and function names must be unique")
    return functions, signatures, structs


def expression_type(expression, variables, signatures, structs, line_number):
    kind = expression[0]
    if kind == "integer":
        if int(expression[1]) > (1 << 63) - 1:
            raise CompileError(f"line {line_number}: integer literal is outside the i64 range")
        return "i64"
    if kind == "boolean":
        return "bool"
    if kind == "name":
        name = expression[1]
        if name not in variables:
            raise CompileError(f"line {line_number}: unknown variable {name!r}")
        return variables[name][1]
    if kind in {"negate", "not"}:
        if kind == "negate" and expression[1][0] == "integer" and int(expression[1][1]) == 1 << 63:
            return "i64"
        operand_type = expression_type(expression[1], variables, signatures, structs, line_number)
        expected_type = "i64" if kind == "negate" else "bool"
        if operand_type != expected_type:
            raise CompileError(f"line {line_number}: operator requires {expected_type}, got {operand_type}")
        return expected_type
    if kind == "array":
        elements = expression[1]
        if not elements:
            raise CompileError(f"line {line_number}: empty arrays need an explicit element type")
        element_type = expression_type(elements[0], variables, signatures, structs, line_number)
        if isinstance(element_type, tuple):
            raise CompileError(f"line {line_number}: nested aggregate values are not supported yet")
        for element in elements[1:]:
            if expression_type(element, variables, signatures, structs, line_number) != element_type:
                raise CompileError(f"line {line_number}: array elements must have the same type")
        return ("array", element_type, len(elements))
    if kind == "index":
        array_type = expression_type(expression[1], variables, signatures, structs, line_number)
        if not isinstance(array_type, tuple) or array_type[0] != "array":
            raise CompileError(f"line {line_number}: indexing requires a fixed-size array")
        if expression_type(expression[2], variables, signatures, structs, line_number) != "i64":
            raise CompileError(f"line {line_number}: array index must be i64")
        return array_type[1]
    if kind == "field":
        value_type = expression_type(expression[1], variables, signatures, structs, line_number)
        if not isinstance(value_type, tuple) or value_type[0] != "struct":
            raise CompileError(f"line {line_number}: field access requires a struct value")
        fields = dict(structs[value_type[1]])
        field_name = expression[2]
        if field_name not in fields:
            raise CompileError(f"line {line_number}: struct {value_type[1]!r} has no field {field_name!r}")
        return fields[field_name]
    if kind == "call":
        _, name, arguments = expression
        if name in structs:
            fields = structs[name]
            if len(arguments) != len(fields):
                raise CompileError(f"line {line_number}: struct {name!r} expects {len(fields)} field values")
            for argument, (field_name, field_type) in zip(arguments, fields):
                if expression_type(argument, variables, signatures, structs, line_number) != field_type:
                    raise CompileError(f"line {line_number}: value for field {field_name!r} must be {field_type}")
            return ("struct", name)
        if name not in signatures:
            raise CompileError(f"line {line_number}: unknown function {name!r}")
        parameters, return_type = signatures[name]
        if len(arguments) != len(parameters):
            raise CompileError(f"line {line_number}: function {name!r} expects {len(parameters)} arguments")
        for argument, (parameter_name, parameter_type) in zip(arguments, parameters):
            argument_type = expression_type(argument, variables, signatures, structs, line_number)
            if argument_type != parameter_type:
                raise CompileError(f"line {line_number}: argument for {parameter_name!r} must be {parameter_type}, got {argument_type}")
        return return_type

    _, operator, left, right = expression
    left_type = expression_type(left, variables, signatures, structs, line_number)
    right_type = expression_type(right, variables, signatures, structs, line_number)
    if operator in {"+", "-", "*", "/", "<", "<=", ">", ">="}:
        if left_type != "i64" or right_type != "i64":
            raise CompileError(f"line {line_number}: operator {operator!r} requires i64 operands")
        return "bool" if operator in {"<", "<=", ">", ">="} else "i64"
    if operator in {"==", "!="}:
        if left_type != right_type:
            raise CompileError(f"line {line_number}: equality operands must have the same type")
        if left_type not in {"i64", "bool"}:
            raise CompileError(f"line {line_number}: equality is only defined for scalar values")
        return "bool"
    if operator in {"&&", "||"}:
        if left_type != "bool" or right_type != "bool":
            raise CompileError(f"line {line_number}: operator {operator!r} requires bool operands")
        return "bool"
    raise CompileError(f"line {line_number}: unsupported operator {operator!r}")


def wrap_i64(value):
    return ((value + (1 << 63)) & ((1 << 64) - 1)) - (1 << 63)


def fold_expression(expression):
    kind = expression[0]
    if kind in {"integer", "boolean", "name"}:
        return expression
    if kind in {"negate", "not"}:
        operand = fold_expression(expression[1])
        if kind == "negate" and operand[0] == "integer" and int(operand[1]) <= (1 << 63) - 1:
            return ("integer", str(wrap_i64(-int(operand[1]))))
        if kind == "not" and operand[0] == "boolean":
            return ("boolean", not operand[1])
        return (kind, operand)
    if kind == "binary":
        _, operator, left, right = expression
        left = fold_expression(left)
        right = fold_expression(right)
        if left[0] == right[0] == "integer":
            left_value = int(left[1])
            right_value = int(right[1])
            if operator == "+":
                return ("integer", str(wrap_i64(left_value + right_value)))
            if operator == "-":
                return ("integer", str(wrap_i64(left_value - right_value)))
            if operator == "*":
                return ("integer", str(wrap_i64(left_value * right_value)))
            if operator == "/" and right_value != 0:
                if left_value == -(1 << 63) and right_value == -1:
                    return ("integer", str(-(1 << 63)))
                quotient = abs(left_value) // abs(right_value)
                if (left_value < 0) != (right_value < 0):
                    quotient = -quotient
                return ("integer", str(quotient))
            comparisons = {
                "==": left_value == right_value,
                "!=": left_value != right_value,
                "<": left_value < right_value,
                "<=": left_value <= right_value,
                ">": left_value > right_value,
                ">=": left_value >= right_value,
            }
            if operator in comparisons:
                return ("boolean", comparisons[operator])
        if left[0] == right[0] == "boolean":
            if operator == "&&":
                return ("boolean", left[1] and right[1])
            if operator == "||":
                return ("boolean", left[1] or right[1])
            if operator == "==":
                return ("boolean", left[1] == right[1])
            if operator == "!=":
                return ("boolean", left[1] != right[1])
        return ("binary", operator, left, right)
    if kind == "call":
        return ("call", expression[1], [fold_expression(argument) for argument in expression[2]])
    if kind == "array":
        return ("array", [fold_expression(value) for value in expression[1]])
    if kind == "index":
        return ("index", fold_expression(expression[1]), fold_expression(expression[2]))
    if kind == "field":
        return ("field", fold_expression(expression[1]), expression[2])
    return expression


@dataclass(frozen=True)
class TypedExpression:
    type: object
    node: tuple


def lower_expression(expression, variables, signatures, structs, line_number):
    value_type = expression_type(expression, variables, signatures, structs, line_number)
    return TypedExpression(value_type, fold_expression(expression))


def c_type(value_type):
    if isinstance(value_type, tuple) and value_type[0] == "struct":
        return f"struct bulb_struct_{value_type[1]}"
    return C_TYPES[value_type]


def emit_expression(typed_expression, variables, signatures, structs, line_number):
    if not isinstance(typed_expression, TypedExpression):
        raise TypeError("code generation requires a typed expression")
    return emit_ast_expression(typed_expression.node, variables, signatures, structs, line_number)


def emit_ast_expression(expression, variables, signatures, structs, line_number):
    kind = expression[0]
    if kind == "integer":
        if int(expression[1]) == -(1 << 63):
            return "INT64_MIN"
        return expression[1]
    if kind == "boolean":
        return "1" if expression[1] else "0"
    if kind == "name":
        return f"bulb_{expression[1]}"
    if kind == "negate":
        if expression[1][0] == "integer" and int(expression[1][1]) == 1 << 63:
            return "INT64_MIN"
        value = emit_ast_expression(expression[1], variables, signatures, structs, line_number)
        return f"bulb_i64_neg({value})"
    if kind == "not":
        value = emit_ast_expression(expression[1], variables, signatures, structs, line_number)
        return f"(!{value})"
    if kind == "array":
        return "{" + ", ".join(emit_ast_expression(value, variables, signatures, structs, line_number) for value in expression[1]) + "}"
    if kind == "index":
        array_type = expression_type(expression[1], variables, signatures, structs, line_number)
        array = emit_ast_expression(expression[1], variables, signatures, structs, line_number)
        index = emit_ast_expression(expression[2], variables, signatures, structs, line_number)
        return f"{array}[bulb_checked_index({index}, {array_type[2]})]"
    if kind == "field":
        value = emit_ast_expression(expression[1], variables, signatures, structs, line_number)
        return f"{value}.bulb_{expression[2]}"
    if kind == "call":
        _, name, arguments = expression
        values = [emit_ast_expression(argument, variables, signatures, structs, line_number) for argument in arguments]
        if name in structs:
            return f"(struct bulb_struct_{name}){{{', '.join(values)}}}"
        return f"bulb_fn_{name}({', '.join(values)})"
    _, operator, left, right = expression
    left_c = emit_ast_expression(left, variables, signatures, structs, line_number)
    right_c = emit_ast_expression(right, variables, signatures, structs, line_number)
    if operator in {"+", "-", "*"}:
        helper = {"+": "add", "-": "sub", "*": "mul"}[operator]
        return f"bulb_i64_{helper}({left_c}, {right_c})"
    if operator == "/":
        return f"bulb_i64_div({left_c}, {right_c})"
    return f"({left_c} {operator} {right_c})"


def emit_statements(statements, variables, signatures, structs, return_type, indentation=4, in_nested_block=False):
    output = []
    prefix = " " * indentation
    for statement in statements:
        if statement[0] == "declare":
            _, name, expression, line_number, mutable = statement
            if in_nested_block:
                raise CompileError(f"line {line_number}: variables must be declared at function scope")
            if name in variables:
                raise CompileError(f"line {line_number}: variable {name!r} is already defined")
            typed_expression = lower_expression(expression, variables, signatures, structs, line_number)
            value_type = typed_expression.type
            if mutable and isinstance(value_type, tuple):
                raise CompileError(f"line {line_number}: aggregate locals are immutable in this version")
            value = emit_expression(typed_expression, variables, signatures, structs, line_number)
            variables[name] = (mutable, value_type)
            qualifier = "" if mutable else "const "
            if isinstance(value_type, tuple) and value_type[0] == "array":
                element_type, length = value_type[1], value_type[2]
                output.append(f"{prefix}{qualifier}{c_type(element_type)} bulb_{name}[{length}] = {value};")
            else:
                output.append(f"{prefix}{qualifier}{c_type(value_type)} bulb_{name} = {value};")
            output.append(f"{prefix}(void)bulb_{name};")
        elif statement[0] == "set":
            _, name, expression, line_number = statement
            if name not in variables:
                raise CompileError(f"line {line_number}: unknown variable {name!r}")
            mutable, variable_type = variables[name]
            if not mutable:
                raise CompileError(f"line {line_number}: cannot assign to immutable variable {name!r}")
            typed_expression = lower_expression(expression, variables, signatures, structs, line_number)
            value_type = typed_expression.type
            if value_type != variable_type:
                raise CompileError(f"line {line_number}: cannot assign {value_type} to {variable_type}")
            value = emit_expression(typed_expression, variables, signatures, structs, line_number)
            output.append(f"{prefix}bulb_{name} = {value};")
        elif statement[0] == "while":
            _, condition, body, line_number = statement
            typed_condition = lower_expression(condition, variables, signatures, structs, line_number)
            if typed_condition.type != "bool":
                raise CompileError(f"line {line_number}: while condition must be bool")
            condition_c = emit_expression(typed_condition, variables, signatures, structs, line_number)
            output.append(f"{prefix}while ({condition_c}) {{")
            output.extend(emit_statements(body, variables, signatures, structs, return_type, indentation + 4, True))
            output.append(f"{prefix}}}")
        elif statement[0] == "if":
            _, condition, true_body, false_body, line_number = statement
            typed_condition = lower_expression(condition, variables, signatures, structs, line_number)
            if typed_condition.type != "bool":
                raise CompileError(f"line {line_number}: if condition must be bool")
            condition_c = emit_expression(typed_condition, variables, signatures, structs, line_number)
            output.append(f"{prefix}if ({condition_c}) {{")
            output.extend(emit_statements(true_body, variables, signatures, structs, return_type, indentation + 4, True))
            if false_body:
                output.append(f"{prefix}}} else {{")
                output.extend(emit_statements(false_body, variables, signatures, structs, return_type, indentation + 4, True))
            output.append(f"{prefix}}}")
        else:
            _, expression, line_number = statement
            typed_expression = lower_expression(expression, variables, signatures, structs, line_number)
            value_type = typed_expression.type
            if value_type != return_type:
                raise CompileError(f"line {line_number}: function returns {return_type}, got {value_type}")
            value = emit_expression(typed_expression, variables, signatures, structs, line_number)
            output.append(f"{prefix}return {value};")
    return output


def c_signature(name, parameters):
    parameter_list, return_type = parameters
    arguments = ", ".join(f"{C_TYPES[value_type]} bulb_{name}" for name, value_type in parameter_list) or "void"
    return f"{C_TYPES[return_type]} bulb_fn_{name}({arguments})"


def compile_source(source, include_entrypoint=True):
    functions, signatures, structs = parse_program(source)
    output = [
        "#include <stdint.h>",
        "#include <stdlib.h>",
        "",
    ]
    for struct_name, fields in structs.items():
        output.append(f"struct bulb_struct_{struct_name} {{")
        output.extend(f"    {C_TYPES[field_type]} bulb_{field_name};" for field_name, field_type in fields)
        output.extend(["};", ""])
    output.extend([
        "static inline uint64_t bulb_checked_index(int64_t index, uint64_t length) {",
        "    if (index < 0 || (uint64_t)index >= length) abort();",
        "    return (uint64_t)index;",
        "}",
        "static inline int64_t bulb_i64_from_bits(uint64_t bits) {",
        "    if (bits <= (uint64_t)INT64_MAX) return (int64_t)bits;",
        "    return -1 - (int64_t)(UINT64_MAX - bits);",
        "}",
        "static inline int64_t bulb_i64_add(int64_t left, int64_t right) {",
        "    return bulb_i64_from_bits((uint64_t)left + (uint64_t)right);",
        "}",
        "static inline int64_t bulb_i64_sub(int64_t left, int64_t right) {",
        "    return bulb_i64_from_bits((uint64_t)left - (uint64_t)right);",
        "}",
        "static inline int64_t bulb_i64_mul(int64_t left, int64_t right) {",
        "    return bulb_i64_from_bits((uint64_t)left * (uint64_t)right);",
        "}",
        "static inline int64_t bulb_i64_neg(int64_t value) {",
        "    return bulb_i64_from_bits(0 - (uint64_t)value);",
        "}",
        "static inline int64_t bulb_i64_div(int64_t left, int64_t right) {",
        "    if (right == 0) abort();",
        "    if (left == INT64_MIN && right == -1) return INT64_MIN;",
        "    return left / right;",
        "}",
        "",
    ])
    output.extend(f"{c_signature(name, signature)};" for name, signature in signatures.items())
    output.append("")

    for name, parameters, return_type, statements, _ in functions:
        variables = {parameter_name: (False, parameter_type) for parameter_name, parameter_type in parameters}
        output.append(f"{c_signature(name, (parameters, return_type))} {{")
        output.extend(f"    (void)bulb_{parameter_name};" for parameter_name, _ in parameters)
        output.extend(emit_statements(statements, variables, signatures, structs, return_type))
        output.extend(["}", ""])

    if include_entrypoint:
        output.extend(["int main(void) {", "    return (int)bulb_fn_main();", "}", ""])
    return "\n".join(output)


def main(argv=None):
    argument_parser = argparse.ArgumentParser(description="Compile a Bulb program to C.")
    argument_parser.add_argument("source", type=Path, help="source file to compile")
    argument_parser.add_argument("-o", "--output", type=Path, help="generated C file (default: SOURCE.c)")
    arguments = argument_parser.parse_args(argv)

    try:
        source = arguments.source.read_text(encoding="utf-8")
        output = compile_source(source)
        output_path = arguments.output or arguments.source.with_suffix(".c")
        output_path.write_text(output, encoding="utf-8")
    except (OSError, CompileError) as error:
        print(f"bulb: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
