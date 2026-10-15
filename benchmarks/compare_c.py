import argparse
import itertools
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bulb import compile_source


def benchmark_sources(workload):
    if workload == "sum":
        function_name = "sum_to"
        bulb_function = """fn sum_to(limit: i64) -> i64:
    var total = 0
    var index = 0
    while index < limit:
        set total = total + index
        set index = index + 1
    return total
"""
        c_source = """#include <stdint.h>

int64_t sum_to(int64_t limit) {
    int64_t total = 0;
    int64_t index = 0;
    while (index < limit) {
        total = total + index;
        index = index + 1;
    }
    return total;
}
"""
        rust_function = """fn sum_to(limit: i64) -> i64 {
    let mut total = 0i64;
    let mut index = 0i64;
    while index < limit {
        total = total.wrapping_add(index);
        index += 1;
    }
    total
}
"""
    elif workload == "fib":
        function_name = "fib"
        bulb_function = """fn fib(n: i64) -> i64:
    if n <= 1:
        return n
    return fib(n - 1) + fib(n - 2)
"""
        c_source = """#include <stdint.h>

int64_t fib(int64_t n) {
    if (n <= 1) {
        return n;
    }
    return fib(n - 1) + fib(n - 2);
}
"""
        rust_function = """fn fib(n: i64) -> i64 {
    if n <= 1 {
        return n;
    }
    fib(n - 1).wrapping_add(fib(n - 2))
}
"""
    else:
        function_name = "sum_array"
        bulb_function = """fn sum_array(rounds: i64) -> i64:
    let values = [1, 2, 3, 4, 5, 6, 7, 8]
    var total = 0
    var index = 0
    var pass = 0
    while pass < rounds:
        while index < 8:
            set total = total + values[index]
            set index = index + 1
        set pass = pass + 1
        if pass < rounds:
            set index = 0
    return total
"""
        c_source = """#include <stdint.h>

int64_t sum_array(int64_t rounds) {
    const int64_t values[8] = {1, 2, 3, 4, 5, 6, 7, 8};
    int64_t total = 0;
    int64_t index = 0;
    int64_t pass = 0;
    while (pass < rounds) {
        while (index < 8) {
            total = total + values[index];
            index = index + 1;
        }
        pass = pass + 1;
        if (pass < rounds) {
            index = 0;
        }
    }
    return total;
}
"""
        rust_function = """fn sum_array(rounds: i64) -> i64 {
    let values = [1i64, 2, 3, 4, 5, 6, 7, 8];
    let mut total = 0i64;
    let mut index = 0usize;
    let mut pass = 0i64;
    while pass < rounds {
        while index < values.len() {
            total = total.wrapping_add(values[index]);
            index += 1;
        }
        pass += 1;
        if pass < rounds {
            index = 0;
        }
    }
    total
}
"""
    bulb_source = f"""fn main() -> i64:
    return {function_name}(1)

{bulb_function}"""
    harness_source = """#include <stdint.h>
#include <stdlib.h>
#include <inttypes.h>
#include <stdio.h>

#ifndef ENTRY
#define ENTRY bulb_fn_sum_to
#endif

extern int64_t ENTRY(int64_t);

int main(int argc, char **argv) {
    if (argc != 2) {
        return 2;
    }
    printf("%" PRId64 "\\n", ENTRY(strtoll(argv[1], NULL, 10)));
    return 0;
}
"""
    rust_source = f"""{rust_function}
fn main() {{
    let size = std::env::args().nth(1).expect("missing workload size").parse::<i64>().expect("invalid workload size");
    let result = {function_name}(size);
    println!("{{}}", result);
}}
"""
    return compile_source(bulb_source, include_entrypoint=False), c_source, harness_source, rust_source, function_name


def main():
    parser = argparse.ArgumentParser(description="Compare Bulb-generated native code with equivalent C.")
    parser.add_argument("--workload", choices=("sum", "fib", "array"), default="sum")
    parser.add_argument("--size", type=int, help="loop bound for sum, or n for fib")
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--cc", default="gcc", help="C compiler (default: gcc)")
    parser.add_argument("--rustc", default=shutil.which("rustc") or str(Path.home() / ".cargo/bin/rustc"))
    arguments = parser.parse_args()
    defaults = {"sum": 50_000_000, "fib": 38, "array": 2_000_000}
    size = arguments.size if arguments.size is not None else defaults[arguments.workload]
    if size < 1 or arguments.samples < 1:
        parser.error("--size and --samples must be positive")
    if arguments.workload == "fib" and size > 92:
        parser.error("fib workload size must not exceed 92 for i64")

    bulb_source, c_source, harness_source, rust_source, entry_symbol = benchmark_sources(arguments.workload)
    if arguments.workload == "sum":
        expected_result = size * (size - 1) // 2
        description = f"sum 0..{size - 1}"
    elif arguments.workload == "fib":
        previous, following = 0, 1
        for _ in range(size):
            previous, following = following, previous + following
        expected_result = previous
        description = f"fib({size})"
    else:
        expected_result = 36 * size
        description = f"sum of fixed array across {size} passes"
    flags = ["-std=c11", "-O2", "-march=native", "-flto", "-Wall", "-Wextra", "-Werror"]

    with tempfile.TemporaryDirectory() as directory:
        directory_path = Path(directory)
        sources = {
            "Bulb-generated C": ("bulb.c", bulb_source, f"bulb_fn_{entry_symbol}"),
            "Handwritten C": ("reference.c", c_source, entry_symbol),
        }
        executables = {}
        for label, (source_name, source_text, entry_symbol) in sources.items():
            source_path = directory_path / source_name
            object_path = directory_path / f"{source_path.stem}.o"
            harness_path = directory_path / f"{source_path.stem}_harness.c"
            harness_object_path = directory_path / f"{source_path.stem}_harness.o"
            executable_path = directory_path / source_path.stem
            source_path.write_text(source_text, encoding="utf-8")
            harness_path.write_text(harness_source, encoding="utf-8")
            subprocess.run([arguments.cc, *flags, "-c", str(source_path), "-o", str(object_path)], check=True)
            subprocess.run(
                [arguments.cc, *flags, f"-DENTRY={entry_symbol}", "-c", str(harness_path), "-o", str(harness_object_path)],
                check=True,
            )
            subprocess.run(
                [arguments.cc, *flags, str(object_path), str(harness_object_path), "-o", str(executable_path)],
                check=True,
            )
            executables[label] = executable_path

        rust_path = directory_path / "reference.rs"
        rust_executable = directory_path / "reference-rust"
        rust_path.write_text(rust_source, encoding="utf-8")
        rust_flags = ["--edition=2021", "-C", "opt-level=2", "-C", "target-cpu=native", "-C", "overflow-checks=off", "-D", "warnings"]
        subprocess.run([arguments.rustc, *rust_flags, str(rust_path), "-o", str(rust_executable)], check=True)
        executables["Rust"] = rust_executable

        timings = {label: [] for label in executables}
        for executable_path in executables.values():
            result = subprocess.run([str(executable_path), str(size)], check=False, capture_output=True, text=True)
            if result.returncode != 0 or result.stdout.strip() != str(expected_result):
                raise RuntimeError(f"unexpected result: expected {expected_result}, got {result.stdout.strip()!r}")

        labels = list(executables)
        for sample in range(arguments.samples):
            rotation = sample % len(labels)
            order = labels[rotation:] + labels[:rotation]
            for label in order:
                start = time.perf_counter()
                result = subprocess.run([str(executables[label]), str(size)], check=False, capture_output=True, text=True)
                timings[label].append(time.perf_counter() - start)
                if result.returncode != 0 or result.stdout.strip() != str(expected_result):
                    raise RuntimeError(f"{label} returned unexpected result {result.stdout.strip()!r}")

    bulb_median = statistics.median(timings["Bulb-generated C"])
    c_median = statistics.median(timings["Handwritten C"])
    rust_median = statistics.median(timings["Rust"])
    print(f"Workload: {description}")
    print(f"C compiler: {arguments.cc} {' '.join(flags)}")
    print(f"Rust compiler: {arguments.rustc} {' '.join(rust_flags)}")
    print(f"Bulb-generated C median: {bulb_median * 1000:.3f} ms")
    print(f"Handwritten C median:    {c_median * 1000:.3f} ms")
    print(f"Rust median:             {rust_median * 1000:.3f} ms")
    print(f"Bulb/C runtime ratio:    {bulb_median / c_median:.3f}x")
    print(f"Bulb/Rust runtime ratio: {bulb_median / rust_median:.3f}x")


if __name__ == "__main__":
    main()