# apreely

High-performance expression evaluator for Python. Parse once, evaluate millions of times.

## Features

- **Data Types**: Integers, Floats, Strings, Booleans, None
- **Arithmetic**: `+`, `-`, `*`, `/`, `//`, `%`, `**`
- **Comparisons**: `==`, `!=`, `<`, `>`, `<=`, `>=`, chained (`1 < x < 10`)
- **Logic**: `and`, `or`, `not`
- **Ternary**: `x if cond else y`
- **Variables**: Dynamic context injection
- **Functions**: Built-in + custom function support
- **Thread-Safe**: Immutable bytecode, no shared mutable state
- **LRU Caching**: Optional cache for compiled expressions

## Quick Start

```python
from apreely import ExpressionEngine

engine = ExpressionEngine()

# Compile once, evaluate many times
expr = engine.compile("2 + 3 * x")
print(expr.evaluate({"x": 10}))  # 32
```

## Installation

Copy `apreely.py` into your project. No dependencies required.

```bash
cp apreely.py /your/project/
```

## Usage

### Basic Math

```python
engine = ExpressionEngine()

expr = engine.compile("2 + 3 * 4")
print(expr.evaluate({}))  # 14

expr = engine.compile("(10 + 5) / 3")
print(expr.evaluate({}))  # 5.0
```

### Variables

```python
expr = engine.compile("x ** 2 + y ** 2")
print(expr.evaluate({"x": 3, "y": 4}))  # 25
```

### Strings

```python
expr = engine.compile('first + " " + last')
print(expr.evaluate({"first": "John", "last": "Doe"}))  # "John Doe"

expr = engine.compile('"Score: " + str(points)')
print(expr.evaluate({"points": 100}))  # "Score: 100"
```

### Logical Operators

```python
expr = engine.compile("x > 0 and y > 0")
print(expr.evaluate({"x": 5, "y": -1}))  # False

expr = engine.compile("x == 0 or y == 0")
print(expr.evaluate({"x": 5, "y": 0}))  # True
```

### Chained Comparisons

```python
expr = engine.compile("1 < x < 10")
print(expr.evaluate({"x": 5}))   # True
print(expr.evaluate({"x": 15}))  # False
```

### Ternary Expressions

```python
expr = engine.compile("x if x > 0 else -x")
print(expr.evaluate({"x": -5}))  # 5

# Nested ternary
expr = engine.compile('"high" if x > 100 else "medium" if x > 10 else "low"')
print(expr.evaluate({"x": 50}))  # "medium"
```

### Built-in Functions

```python
expr = engine.compile("abs(x) + max(a, b)")
print(expr.evaluate({"x": -5, "a": 10, "b": 20}))  # 25

expr = engine.compile("len(name) > 0")
print(expr.evaluate({"name": "Alice"}))  # True

# Coalesce (first non-None value)
expr = engine.compile("coalesce(x, y, z)")
print(expr.evaluate({"x": None, "y": 5, "z": 10}))  # 5

# NullIf (returns None if equal)
expr = engine.compile("nullif(x, y)")
print(expr.evaluate({"x": 5, "y": 5}))   # None
print(expr.evaluate({"x": 5, "y": 10}))  # 5
```

**Available built-in functions:**

| Function | Description |
|----------|-------------|
| `abs(x)` | Absolute value |
| `round(x)` | Round to nearest integer |
| `min(a, b)` | Minimum value |
| `max(a, b)` | Maximum value |
| `len(x)` | Length of string/collection |
| `int(x)` | Convert to integer |
| `float(x)` | Convert to float |
| `str(x)` | Convert to string |
| `bool(x)` | Convert to boolean |
| `is_none(x)` | Check if value is None |
| `is_not_none(x)` | Check if value is not None |
| `coalesce(a, b, ...)` | First non-None value |
| `nullif(a, b)` | None if a == b, else a |

### Custom Functions

```python
def square(n):
    return n ** 2

def clamp(value, min_val, max_val):
    return max(min_val, min(max_val, value))

expr = engine.compile("square(x) + square(y)")
print(expr.evaluate(
    {"x": 3, "y": 4},
    functions={"square": square}
))  # 25

expr = engine.compile("clamp(x * 2, 0, 100)")
print(expr.evaluate(
    {"x": 60},
    functions={"clamp": clamp}
))  # 100
```

## Error Handling

### Undefined Variables

```python
from apreely import ExpressionEngine

engine = ExpressionEngine()

try:
    expr = engine.compile("x + y")
    result = expr.evaluate({"x": 5})  # y is undefined
except KeyError as e:
    print(f"Error: {e}")
    # Error: Undefined variable: 'y'
```

### Division by Zero

```python
try:
    result = engine.evaluate("x / y", {"x": 10, "y": 0})
except EvaluationError as e:
    print(f"Error: {e}")
    # Error: Division by zero: division by zero
```

### All Exceptions Are Logged

Every error is logged via Python's `logging` module before being raised:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# This will log:
# ERROR:apreely:Undefined variable: 'y'
engine.evaluate("x + y", {"x": 5})
```

## Thread Safety

The library is thread-safe. Compiled expressions use immutable bytecode and evaluation uses only local state.

```python
from concurrent.futures import ThreadPoolExecutor
from apreely import ExpressionEngine

engine = ExpressionEngine()
expr = engine.compile("x ** 2 + y ** 2")

def compute(params):
    return expr.evaluate(params)

tasks = [{"x": i, "y": i * 2} for i in range(1000)]

with ThreadPoolExecutor(max_workers=8) as pool:
    results = list(pool.map(compute, tasks))
```

## Caching

Enable LRU caching to avoid re-parsing the same expression:

```python
engine = ExpressionEngine(cache_size=128)

# First call: compiles and caches
engine.evaluate("x + 1", {"x": 1})

# Second call: reuses cached bytecode
engine.evaluate("x + 1", {"x": 2})

# Cache management
print(engine.cache_current)       # Number of cached expressions
print(engine.cache_size)          # Maximum cache size
engine.clear_cache()              # Clear all cached expressions
engine.get_cached_expressions()   # List of cached expression strings
```

Disable caching:

```python
engine = ExpressionEngine(cache_size=0)
```

## Performance

| Operation | Time |
|-----------|------|
| Compile | ~10-50μs |
| Evaluate | ~0.5-2μs |
| Throughput | ~500K-2M evals/sec |

The engine separates parsing from execution. Compile once, evaluate millions of times.

## Examples

Run the example files in the `examples/` directory:

```bash
python3 examples/basic_math.py
python3 examples/string_operations.py
python3 examples/logical_operators.py
python3 examples/ternary_expressions.py
python3 examples/functions.py
python3 examples/error_handling.py
python3 examples/thread_safety.py
python3 examples/caching.py
python3 examples/real_world.py
```

Or use the menu:

```bash
python3 examples/run_examples.py
```

## API Reference

### `ExpressionEngine(cache_size=128)`

Main entry point for the expression evaluator.

**Parameters:**
- `cache_size` (int): Maximum number of compiled expressions to cache. Default: 128. Set to 0 to disable.

**Methods:**
- `compile(expression: str) -> CompiledExpression`: Parse and compile an expression.
- `evaluate(expression: str, context: dict, functions: dict = None) -> Any`: Compile and evaluate in one step.
- `clear_cache() -> None`: Clear all cached expressions.
- `get_cached_expressions() -> List[str]`: List cached expression strings.

### `CompiledExpression`

Immutable, thread-safe compiled expression.

**Methods:**
- `evaluate(context: dict, functions: dict = None) -> Any`: Evaluate with given context.

**Properties:**
- `variables`: Tuple of required variable names.

### Exceptions

- `ExpressionError`: Base exception for parsing/compilation errors.
- `EvaluationError`: Exception for runtime evaluation errors (division by zero, etc.).
- `KeyError`: Raised for undefined variables or functions.

## License

MIT
