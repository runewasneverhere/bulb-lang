# Bulb

Bulb is an experimental programming language aiming for approachable syntax and native-code performance. This first prototype compiles a deliberately small language subset to C; GCC then produces the executable.

## Requirements

- Python 3
- GCC
- Stable Rust via rustup for three-way benchmarks

## Example

```text
fn main() -> i64:
    let answer = 6 * 7
    return answer
```

Compile and run it:

```sh
python3 bulb.py examples/answer.bulb -o /tmp/answer.c
gcc -std=c11 -O2 /tmp/answer.c -o /tmp/answer
/tmp/answer
```

The example exits with status `42`.

## Current scope

The prototype supports user-defined functions with `i64` or `bool` parameters and results, inferred local types, function calls, `if`/`else`, nested `while` loops, fixed-size array literals, and structs. `let` declares an immutable local; `var` declares a mutable scalar and `set` updates it. Comparisons and short-circuit boolean operators are available. Arrays and structs are inline values; array indexing is bounds-checked. There are no pointers, dynamic allocation, or mutable aggregate locals yet. Function bodies must return on every path; declarations inside nested blocks and returns from inside loops are not supported yet.

The compiler itself is currently written in Python and emits C. This demonstrates a path to native machine code, not performance parity with C or Rust. `i64` arithmetic wraps modulo $2^{64}$, division truncates toward zero, division by zero aborts, and `INT64_MIN / -1` wraps to `INT64_MIN`. The current memory model uses stack-allocated fixed arrays and value structs; there is no heap or pointer model yet. Performance coverage is still a single microbenchmark.

The [`sum_to.bulb`](examples/sum_to.bulb) example exercises a function call and a loop.
# bulb

bulb is a small experimental language. its compiler is written in python, turns `.bulb` files into c, and uses gcc to build a native executable. the compiler does not run when that executable runs.

## what you need

- python 3 and gcc to compile bulb programs
- rust, installed with rustup, to run the three-language benchmarks

## try it

```text
fn main() -> i64:
    let answer = 6 * 7
    return answer
```

the same program is in [`examples/answer.bulb`](examples/answer.bulb). compile it and run it:

```sh
python3 bulb.py examples/answer.bulb -o /tmp/answer.c
gcc -std=c11 -O2 /tmp/answer.c -o /tmp/answer
/tmp/answer
```

the program exits with status `42`.

## what works

- functions with `i64` or `bool` parameters and return values
- inferred local types, immutable `let` values, and mutable scalar `var` values updated with `set`
- arithmetic, comparisons, boolean operators, function calls, `if`/`else`, and `while`
- fixed-size arrays and structs stored inline; array access checks bounds

`i64` arithmetic wraps to 64 bits. division truncates toward zero, division by zero aborts, and `INT64_MIN / -1` returns `INT64_MIN`. locals must be declared at function scope. there are no pointers, heap allocation, mutable arrays or structs, or returns from inside loops yet.

## compare speed

the benchmark runs equivalent loop, recursive fibonacci, and array programs in bulb, c, and rust. it checks their full results, then reports the median of five runs:

```sh
python3 benchmarks/compare_c.py --workload sum
python3 benchmarks/compare_c.py --workload fib
python3 benchmarks/compare_c.py --workload array
```

use `--size N` to change the workload size. compilation is not timed; process startup and printing are. gcc uses `-O2 -march=native -flto`, and rustc uses `opt-level=2` with the native cpu. the compilers may optimize the same source differently: for example, rust can replace the sum loop with a formula. these numbers describe these programs on your machine, not the overall speed of bulb.

## tests

```sh
python3 -m unittest discover -s tests -v
```

## windows installer

version tags create a Windows installer in the GitHub release. the installer adds `bulb.exe` and the examples, and can add Bulb to your user `PATH`. Python is not needed after installation. Bulb currently emits C; compiling that C to a native program still requires a Windows C compiler such as GCC.