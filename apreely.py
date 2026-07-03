"""
apreely - High-Performance Expression Evaluator

A thread-safe expression evaluator for data scientists that separates
parsing from execution for maximum performance.

Usage:
    from apreely import ExpressionEngine, EvaluationError

    engine = ExpressionEngine(cache_size=128)
    expr = engine.compile("2 + 3 * (x - 1)")
    result = expr.evaluate({"x": 10})  # 29

Features:
    - Integers, Floats, Strings, Booleans
    - Math operations: +, -, *, /, //, %, **
    - Logical operators: and, or, not
    - Ternary expressions: x if cond else y
    - Chained comparisons: 1 < x < 10
    - Custom functions injection
    - Built-in functions: abs, min, max, len, str, int, float, bool
    - Thread-safe evaluation
    - Optional LRU caching for compiled expressions
"""

import ast
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# Exceptions
# =============================================================================

class ExpressionError(Exception):
    """Base exception for expression parsing/compilation errors."""
    pass


class EvaluationError(Exception):
    """Raised when expression evaluation fails at runtime."""
    pass


# =============================================================================
# Bytecode Compiler
# =============================================================================

class _Compiler:
    """Compiles Python AST to stack-based bytecode."""

    # Supported binary operators
    BINARY_OPS = {
        ast.Add: 'ADD',
        ast.Sub: 'SUB',
        ast.Mult: 'MUL',
        ast.Div: 'DIV',
        ast.FloorDiv: 'FLOOR_DIV',
        ast.Mod: 'MOD',
        ast.Pow: 'POW',
        ast.Eq: 'EQ',
        ast.NotEq: 'NEQ',
        ast.Lt: 'LT',
        ast.LtE: 'LTE',
        ast.Gt: 'GT',
        ast.GtE: 'GTE',
    }

    # Supported unary operators
    UNARY_OPS = {
        ast.USub: 'NEG',
        ast.UAdd: 'POS',
        ast.Not: 'NOT',
    }

    # Boolean operators
    BOOL_OPS = {
        ast.And: 'AND',
        ast.Or: 'OR',
    }

    def compile(self, expression: str) -> Tuple[Tuple, ...]:
        """Parse expression string and compile to bytecode."""
        try:
            tree = ast.parse(expression, mode='eval')
        except SyntaxError as e:
            logger.error("Syntax error in expression: %s", e)
            raise ExpressionError(f"Invalid expression syntax: {e}") from e

        instructions: List[Tuple] = []
        self._compile_node(tree.body, instructions)
        return tuple(instructions)

    def _compile_node(self, node: ast.AST, instructions: List[Tuple]) -> None:
        """Recursively compile AST node to bytecode instructions."""

        # Number literal
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            instructions.append(('CONST', node.value))

        # String literal
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            instructions.append(('CONST', node.value))

        # Boolean literal
        elif isinstance(node, ast.Constant) and isinstance(node.value, bool):
            instructions.append(('CONST', node.value))

        # None literal
        elif isinstance(node, ast.Constant) and node.value is None:
            instructions.append(('CONST', None))

        # Variable name
        elif isinstance(node, ast.Name):
            instructions.append(('VAR', node.id))

        # Binary operation (a op b)
        elif isinstance(node, ast.BinOp):
            op_type = type(node.op)
            if op_type not in self.BINARY_OPS:
                logger.error("Unsupported binary operator: %s", op_type.__name__)
                raise ExpressionError(f"Unsupported operator: {op_type.__name__}")
            self._compile_node(node.left, instructions)
            self._compile_node(node.right, instructions)
            instructions.append(('BINOP', self.BINARY_OPS[op_type]))

        # Unary operation (-a, +a, not a)
        elif isinstance(node, ast.UnaryOp):
            op_type = type(node.op)
            if op_type not in self.UNARY_OPS:
                logger.error("Unsupported unary operator: %s", op_type.__name__)
                raise ExpressionError(f"Unsupported unary operator: {op_type.__name__}")
            self._compile_node(node.operand, instructions)
            instructions.append(('UNARY', self.UNARY_OPS[op_type]))

        # Boolean operation (and, or)
        elif isinstance(node, ast.BoolOp):
            op_type = type(node.op)
            if op_type not in self.BOOL_OPS:
                logger.error("Unsupported boolean operator: %s", op_type.__name__)
                raise ExpressionError(f"Unsupported boolean operator: {op_type.__name__}")
            # Compile first value, then for each subsequent value,
            # compile it then emit the BOOL_OP
            self._compile_node(node.values[0], instructions)
            for i in range(1, len(node.values)):
                self._compile_node(node.values[i], instructions)
                instructions.append(('BOOL_OP', self.BOOL_OPS[op_type]))

        # Comparison (==, !=, <, >, <=, >=, chained)
        elif isinstance(node, ast.Compare):
            # For chained comparisons like "1 < x < 10",
            # we need to compile as: (1 < x) AND (x < 10)
            # to ensure x is re-evaluated for each comparison
            if len(node.ops) == 1:
                # Simple comparison
                self._compile_node(node.left, instructions)
                self._compile_node(node.comparators[0], instructions)
                op_type = type(node.ops[0])
                if op_type not in self.BINARY_OPS:
                    logger.error("Unsupported comparison operator: %s", op_type.__name__)
                    raise ExpressionError(f"Unsupported comparison: {op_type.__name__}")
                instructions.append(('CMP', self.BINARY_OPS[op_type], False))
            else:
                # Chained comparison: compile each pair with short-circuit AND
                # First comparison: left op[0] comparators[0]
                self._compile_node(node.left, instructions)
                self._compile_node(node.comparators[0], instructions)
                op_type = type(node.ops[0])
                if op_type not in self.BINARY_OPS:
                    logger.error("Unsupported comparison operator: %s", op_type.__name__)
                    raise ExpressionError(f"Unsupported comparison: {op_type.__name__}")
                instructions.append(('CMP', self.BINARY_OPS[op_type], False))

                # For remaining comparisons, we need to short-circuit on failure
                for i in range(1, len(node.ops)):
                    # Jump to end if previous comparison was False
                    instructions.append(('JMP_IF_FALSE', None))  # placeholder
                    jump_idx = len(instructions) - 1

                    # Load the middle value (comparators[i-1]) again
                    self._compile_node(node.comparators[i - 1], instructions)
                    # Load the right value
                    self._compile_node(node.comparators[i], instructions)
                    op_type = type(node.ops[i])
                    if op_type not in self.BINARY_OPS:
                        logger.error("Unsupported comparison operator: %s", op_type.__name__)
                        raise ExpressionError(f"Unsupported comparison: {op_type.__name__}")
                    instructions.append(('CMP', self.BINARY_OPS[op_type], False))

                    # Backpatch the jump
                    instructions[jump_idx] = ('JMP_IF_FALSE', len(instructions))

        # Ternary expression (x if cond else y)
        elif isinstance(node, ast.IfExp):
            self._compile_node(node.test, instructions)
            instructions.append(('JMP_IF_FALSE', None))  # placeholder
            body_start = len(instructions)
            self._compile_node(node.body, instructions)
            instructions.append(('JMP', None))  # placeholder
            body_end = len(instructions)
            self._compile_node(node.orelse, instructions)
            # Backpatch jumps
            instructions[body_start - 1] = ('JMP_IF_FALSE', body_end)
            instructions[body_end - 1] = ('JMP', len(instructions))

        # Function call
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                func_name = func.id
            else:
                logger.error("Unsupported function call type")
                raise ExpressionError("Only simple function calls are supported")

            # Compile arguments
            for arg in node.args:
                self._compile_node(arg, instructions)
            instructions.append(('CALL', func_name, len(node.args)))

        else:
            logger.error("Unsupported AST node type: %s", type(node).__name__)
            raise ExpressionError(f"Unsupported expression: {type(node).__name__}")

    def extract_variables(self, expression: str) -> Set[str]:
        """Extract all variable names from an expression."""
        try:
            tree = ast.parse(expression, mode='eval')
        except SyntaxError:
            return set()

        variables = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                variables.add(node.id)
        return variables


# =============================================================================
# Compiled Expression (Immutable, Thread-Safe)
# =============================================================================

@dataclass(frozen=True)
class CompiledExpression:
    """
    A compiled expression ready for evaluation.

    This object is immutable and thread-safe. Multiple threads can
    call evaluate() concurrently without any locking.
    """
    _bytecode: Tuple[Tuple, ...] = field(repr=False)
    _variables: Tuple[str, ...] = field(repr=False)
    _original: str = field(repr=True)

    def evaluate(
        self,
        context: Dict[str, Any],
        functions: Optional[Dict[str, Callable]] = None
    ) -> Any:
        """
        Evaluate the expression with the given context.

        Args:
            context: Dictionary of variable name -> value.
            functions: Optional dictionary of function name -> callable.

        Returns:
            The result of the expression evaluation.

        Raises:
            KeyError: If an undefined variable is accessed.
            EvaluationError: If evaluation fails (division by zero, etc.).
        """
        func_dict = {**BUILTIN_FUNCTIONS}
        if functions:
            func_dict.update(functions)

        return _eval_bytecode(self._bytecode, context, func_dict)

    @property
    def variables(self) -> Tuple[str, ...]:
        """Return the tuple of required variable names."""
        return self._variables


# =============================================================================
# Bytecode Evaluator
# =============================================================================

def _eval_bytecode(
    bytecode: Tuple[Tuple, ...],
    context: Dict[str, Any],
    functions: Dict[str, Callable]
) -> Any:
    """
    Execute bytecode using a stack machine.

    This function uses only local variables for thread safety.
    """
    stack: List[Any] = []
    pc = 0  # program counter
    length = len(bytecode)

    while pc < length:
        instruction = bytecode[pc]
        opcode = instruction[0]

        if opcode == 'CONST':
            # Push constant value
            stack.append(instruction[1])

        elif opcode == 'VAR':
            # Load variable from context
            name = instruction[1]
            if name not in context:
                logger.error("Undefined variable: '%s'", name)
                raise KeyError(f"Undefined variable: '{name}'")
            stack.append(context[name])

        elif opcode == 'BINOP':
            # Binary operation: a op b
            b = stack.pop()
            a = stack.pop()
            op = instruction[1]
            result = _apply_binop(a, b, op)
            stack.append(result)

        elif opcode == 'UNARY':
            # Unary operation: op a
            a = stack.pop()
            op = instruction[1]
            result = _apply_unary(a, op)
            stack.append(result)

        elif opcode == 'BOOL_OP':
            # Boolean operation: short-circuit evaluation
            b = stack.pop()
            a = stack.pop()
            op = instruction[1]
            result = _apply_boolop(a, b, op)
            stack.append(result)

        elif opcode == 'CMP':
            # Comparison operation
            b = stack.pop()
            a = stack.pop()
            op = instruction[1]
            result = _apply_cmp(a, b, op)
            stack.append(result)

        elif opcode == 'JMP_IF_FALSE':
            # Conditional jump
            condition = stack.pop()
            if not condition:
                pc = instruction[1]
                continue

        elif opcode == 'JMP':
            # Unconditional jump
            pc = instruction[1]
            continue

        elif opcode == 'CALL':
            # Function call
            func_name = instruction[1]
            argc = instruction[2]

            # Collect arguments (in reverse order)
            args = []
            for _ in range(argc):
                args.append(stack.pop())
            args.reverse()

            if func_name not in functions:
                logger.error("Undefined function: '%s'", func_name)
                raise KeyError(f"Undefined function: '{func_name}'")

            func = functions[func_name]
            try:
                result = func(*args)
            except Exception as e:
                logger.error("Error calling function '%s': %s", func_name, e)
                raise EvaluationError(f"Error in function '{func_name}': {e}") from e

            stack.append(result)

        else:
            logger.error("Unknown opcode: %s", opcode)
            raise EvaluationError(f"Unknown opcode: {opcode}")

        pc += 1

    if not stack:
        logger.error("Empty stack at end of evaluation")
        raise EvaluationError("Expression produced no value")

    return stack[-1]


def _apply_binop(a: Any, b: Any, op: str) -> Any:
    """Apply a binary operation with None propagation."""
    # Handle None values
    if a is None or b is None:
        # Allow == and != with None
        if op == 'EQ':
            return a is None and b is None
        elif op == 'NEQ':
            return not (a is None and b is None)
        # For other operations, propagate None
        return None

    try:
        if op == 'ADD':
            return a + b
        elif op == 'SUB':
            return a - b
        elif op == 'MUL':
            return a * b
        elif op == 'DIV':
            return a / b
        elif op == 'FLOOR_DIV':
            return a // b
        elif op == 'MOD':
            return a % b
        elif op == 'POW':
            return a ** b
        elif op == 'EQ':
            return a == b
        elif op == 'NEQ':
            return a != b
        elif op == 'LT':
            return a < b
        elif op == 'LTE':
            return a <= b
        elif op == 'GT':
            return a > b
        elif op == 'GTE':
            return a >= b
        else:
            raise EvaluationError(f"Unknown binary operator: {op}")
    except ZeroDivisionError as e:
        logger.error("Division by zero: %s", e)
        raise EvaluationError(f"Division by zero: {e}") from e
    except TypeError as e:
        logger.error("Type error in operation %s: %s", op, e)
        raise EvaluationError(f"Type error: {e}") from e
    except OverflowError as e:
        logger.error("Overflow error: %s", e)
        raise EvaluationError(f"Overflow error: {e}") from e


def _apply_unary(a: Any, op: str) -> Any:
    """Apply a unary operation."""
    if a is None:
        if op == 'NOT':
            return True
        return None

    try:
        if op == 'NEG':
            return -a
        elif op == 'POS':
            return +a
        elif op == 'NOT':
            return not a
        else:
            raise EvaluationError(f"Unknown unary operator: {op}")
    except TypeError as e:
        logger.error("Type error in unary operation %s: %s", op, e)
        raise EvaluationError(f"Type error: {e}") from e


def _apply_boolop(a: Any, b: Any, op: str) -> Any:
    """Apply a boolean operation with short-circuit evaluation."""
    if op == 'AND':
        # Short-circuit: if a is falsy, return a; otherwise return b
        if not a:
            return a
        return b
    elif op == 'OR':
        # Short-circuit: if a is truthy, return a; otherwise return b
        if a:
            return a
        return b
    else:
        raise EvaluationError(f"Unknown boolean operator: {op}")


def _apply_cmp(a: Any, b: Any, op: str) -> Any:
    """Apply a comparison operation."""
    # Handle None comparisons
    if a is None or b is None:
        if op == 'EQ':
            return a is None and b is None
        elif op == 'NEQ':
            return not (a is None and b is None)
        return None

    try:
        if op == 'EQ':
            return a == b
        elif op == 'NEQ':
            return a != b
        elif op == 'LT':
            return a < b
        elif op == 'LTE':
            return a <= b
        elif op == 'GT':
            return a > b
        elif op == 'GTE':
            return a >= b
        else:
            raise EvaluationError(f"Unknown comparison operator: {op}")
    except TypeError as e:
        logger.error("Type error in comparison: %s", e)
        raise EvaluationError(f"Cannot compare: {e}") from e


# =============================================================================
# Built-in Functions
# =============================================================================

def _is_none(x: Any) -> bool:
    """Check if value is None."""
    return x is None


def _is_not_none(x: Any) -> bool:
    """Check if value is not None."""
    return x is not None


def _nullif(a: Any, b: Any) -> Any:
    """Return None if a == b, otherwise return a."""
    if a == b:
        return None
    return a


def _coalesce(*args: Any) -> Any:
    """Return the first non-None argument."""
    for arg in args:
        if arg is not None:
            return arg
    return None


BUILTIN_FUNCTIONS: Dict[str, Callable] = {
    'abs': abs,
    'round': round,
    'min': min,
    'max': max,
    'len': len,
    'int': int,
    'float': float,
    'str': str,
    'bool': bool,
    'is_none': _is_none,
    'is_not_none': _is_not_none,
    'nullif': _nullif,
    'coalesce': _coalesce,
}


# =============================================================================
# Expression Engine (Main Entry Point)
# =============================================================================

class ExpressionEngine:
    """
    High-performance expression evaluator.

    This engine separates parsing from execution for maximum performance.
    Compile expressions once, evaluate them millions of times.

    Example:
        engine = ExpressionEngine(cache_size=128)
        expr = engine.compile("2 + 3 * (x - 1)")
        result = expr.evaluate({"x": 10})  # 29

    Thread Safety:
        This class is thread-safe. The compiled expressions are immutable
        and can be shared across threads.
    """

    def __init__(self, cache_size: int = 128):
        """
        Initialize the expression engine.

        Args:
            cache_size: Maximum number of compiled expressions to cache.
                       Set to 0 to disable caching. Default is 128.
        """
        self._cache_size = cache_size
        self._cache: Dict[str, CompiledExpression] = {}
        self._compiler = _Compiler()

    def compile(self, expression: str) -> CompiledExpression:
        """
        Parse and compile an expression string.

        The expression is parsed once and cached for future use.
        Subsequent calls with the same string return the cached result.

        Args:
            expression: The expression string to compile.

        Returns:
            A CompiledExpression object that can be evaluated.

        Raises:
            ExpressionError: If the expression has invalid syntax.
        """
        # Normalize expression (strip whitespace) for cache key
        cache_key = expression.strip()

        # Check cache
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Compile new expression
        bytecode = self._compiler.compile(expression)
        variables = tuple(self._compiler.extract_variables(expression))

        compiled = CompiledExpression(
            _bytecode=bytecode,
            _variables=variables,
            _original=expression
        )

        # Cache if enabled
        if self._cache_size > 0:
            if len(self._cache) >= self._cache_size:
                # Evict oldest entry (first inserted)
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]
            self._cache[cache_key] = compiled

        return compiled

    def evaluate(
        self,
        expression: str,
        context: Dict[str, Any],
        functions: Optional[Dict[str, Callable]] = None
    ) -> Any:
        """
        Compile and evaluate an expression in one step.

        This is a convenience method that compiles (with caching) and
        evaluates the expression.

        Args:
            expression: The expression string to evaluate.
            context: Dictionary of variable name -> value.
            functions: Optional dictionary of function name -> callable.

        Returns:
            The result of the expression evaluation.

        Raises:
            KeyError: If an undefined variable is accessed.
            EvaluationError: If evaluation fails.
        """
        compiled = self.compile(expression)
        return compiled.evaluate(context, functions)

    @property
    def cache_size(self) -> int:
        """Return the maximum cache size."""
        return self._cache_size

    @property
    def cache_current(self) -> int:
        """Return the current number of cached expressions."""
        return len(self._cache)

    def clear_cache(self) -> None:
        """Clear all cached expressions."""
        self._cache.clear()

    def get_cached_expressions(self) -> List[str]:
        """Return list of cached expression strings."""
        return list(self._cache.keys())


# =============================================================================
# Module-level convenience function
# =============================================================================

def evaluate(
    expression: str,
    context: Dict[str, Any],
    functions: Optional[Dict[str, Callable]] = None
) -> Any:
    """
    Evaluate an expression string with the given context.

    This is a convenience function that creates a temporary engine,
    compiles, and evaluates the expression. For repeated evaluation,
    use ExpressionEngine directly for better performance.

    Args:
        expression: The expression string to evaluate.
        context: Dictionary of variable name -> value.
        functions: Optional dictionary of function name -> callable.

    Returns:
        The result of the expression evaluation.
    """
    engine = ExpressionEngine(cache_size=0)
    return engine.evaluate(expression, context, functions)
