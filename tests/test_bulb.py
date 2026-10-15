import subprocess
import tempfile
import unittest
from pathlib import Path

from bulb import CompileError, compile_source


class CompilerTests(unittest.TestCase):
    def compile_and_run(self, source):
        generated_c = compile_source(source)
        with tempfile.TemporaryDirectory() as directory:
            c_path = Path(directory) / "program.c"
            executable_path = Path(directory) / "program"
            c_path.write_text(generated_c, encoding="utf-8")
            subprocess.run(
                ["gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", str(c_path), "-o", str(executable_path)],
                check=True,
            )
            result = subprocess.run([str(executable_path)], check=False, cwd=directory)
        return result.returncode

    def compile_and_capture_i64(self, source):
        generated_c = compile_source(source, include_entrypoint=False)
        harness = """#include <inttypes.h>
#include <stdio.h>

int64_t bulb_fn_main(void);

int main(void) {
    printf("%" PRId64 "\\n", bulb_fn_main());
    return 0;
}
"""
        with tempfile.TemporaryDirectory() as directory:
            c_path = Path(directory) / "program.c"
            executable_path = Path(directory) / "program"
            c_path.write_text(generated_c + harness, encoding="utf-8")
            subprocess.run(
                ["gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", str(c_path), "-o", str(executable_path)],
                check=True,
            )
            result = subprocess.run([str(executable_path)], check=True, capture_output=True, text=True)
        return int(result.stdout)

    def test_compiles_and_runs_native_program(self):
        source = "fn main() -> i64:\n    let answer = 6 * 7\n    return answer\n"
        self.assertEqual(self.compile_and_run(source), 42)

    def test_i64_addition_wraps(self):
        source = "fn main() -> i64:\n    return 9223372036854775807 + 1\n"
        self.assertEqual(self.compile_and_capture_i64(source), -9223372036854775808)

    def test_constant_expression_is_folded(self):
        source = "fn main() -> i64:\n    return 2 + 3 * 4\n"
        generated_c = compile_source(source)
        self.assertIn("int64_t bulb_fn_main(void) {\n    return 14;", generated_c)

    def test_integer_division_truncates_toward_zero(self):
        source = "fn main() -> i64:\n    return -7 / 3\n"
        self.assertEqual(self.compile_and_capture_i64(source), -2)

    def test_bool_function_and_if_else(self):
        source = """fn main() -> i64:
    if is_positive(4):
        return 1
    else:
        return 0

fn is_positive(value: i64) -> bool:
    return value > 0
"""
        self.assertEqual(self.compile_and_run(source), 1)

    def test_fixed_array_and_value_struct(self):
        source = """struct Pair:
    left: i64
    right: i64

fn main() -> i64:
    let values = [20, 22]
    let pair = Pair(values[0], values[1])
    return pair.left + pair.right
"""
        self.assertEqual(self.compile_and_run(source), 42)

    def test_mutable_array_elements(self):
        source = """fn main() -> i64:
    var values = [1, 2]
    set values[0] = 40
    set values[1] = 2
    return values[0] + values[1]
"""
        self.assertEqual(self.compile_and_run(source), 42)

    def test_owned_heap_array_and_early_return_cleanup(self):
        source = """fn main() -> i64:
    var values = heap_array(3, 0)
    set values[0] = 10
    set values[1] = 20
    set values[2] = 9
    if values.length == 3:
        return values[0] + values[1] + values[2] + values.length
    else:
        return -1
"""
        generated_c = compile_source(source)
        self.assertEqual(generated_c.count("bulb_heap_i64_destroy(bulb_values.data);"), 2)
        self.assertEqual(self.compile_and_run(source), 42)

    def test_heap_array_return_inside_loop_reads_before_cleanup(self):
        source = """fn main() -> i64:
    var values = heap_array(1, 42)
    while true:
        return values[0]
    return 0
"""
        self.assertEqual(self.compile_and_run(source), 42)

    def test_empty_heap_array_has_zero_length(self):
        source = "fn main() -> i64:\n    let values = heap_array(0, 0)\n    return values.length\n"
        self.assertEqual(self.compile_and_run(source), 0)

    def test_unsafe_pointer_allocation_and_function_calls(self):
        source = """fn read_first(pointer: ptr_i64) -> i64:
    return unsafe_load_i64(pointer, 0)

fn main() -> i64:
    var pointer = unsafe_alloc_i64(1)
    unsafe_store_i64(pointer, 0, 42)
    let value = read_first(pointer)
    unsafe_free_i64(pointer)
    return value
"""
        self.assertEqual(self.compile_and_run(source), 42)

    def test_rejects_copying_owned_heap_array(self):
        source = """fn main() -> i64:
    var values = heap_array(2, 0)
    let copy = values
    return copy.length
"""
        with self.assertRaisesRegex(CompileError, "heap arrays cannot be copied"):
            compile_source(source)

    def test_mutable_struct_fields(self):
        source = """struct Pair:
    left: i64
    right: i64

fn main() -> i64:
    var pair = Pair(0, 0)
    set pair.left = 42
    return pair.left
"""
        self.assertEqual(self.compile_and_run(source), 42)

    def test_return_inside_loop(self):
        source = """fn main() -> i64:
    var index = 0
    while index < 5:
        if index == 3:
            return index
        set index = index + 1
    return -1
"""
        self.assertEqual(self.compile_and_run(source), 3)

    def test_nested_locals_have_block_scope(self):
        source = """fn main() -> i64:
    let value = 1
    if true:
        let value = 42
    return value
"""
        self.assertEqual(self.compile_and_run(source), 1)

    def test_rejects_mutating_immutable_array(self):
        source = """fn main() -> i64:
    let values = [1, 2]
    set values[0] = 3
    return 0
"""
        with self.assertRaisesRegex(CompileError, "cannot assign to immutable variable 'values'"):
            compile_source(source)

    def test_array_index_is_bounds_checked(self):
        source = """fn main() -> i64:
    let values = [10, 20]
    var index = 2
    return values[index]
"""
        self.assertLess(self.compile_and_run(source), 0)

    def test_rejects_integer_as_condition(self):
        source = """fn main() -> i64:
    if 1:
        return 1
    else:
        return 0
"""
        with self.assertRaisesRegex(CompileError, "if condition must be bool"):
            compile_source(source)

    def test_rejects_mixed_type_assignment(self):
        source = """fn main() -> i64:
    var flag = true
    set flag = 1
    return 0
"""
        with self.assertRaisesRegex(CompileError, "cannot assign i64 to bool"):
            compile_source(source)

    def test_rejects_mixed_array_element_types(self):
        source = "fn main() -> i64:\n    let values = [1, true]\n    return 0\n"
        with self.assertRaisesRegex(CompileError, "array elements must have the same type"):
            compile_source(source)

    def test_compiles_function_calls_and_loops(self):
        example_path = Path(__file__).resolve().parents[1] / "examples" / "sum_to.bulb"
        source = example_path.read_text(encoding="utf-8")
        self.assertEqual(self.compile_and_run(source), 45)

    def test_rejects_unknown_variable(self):
        source = "fn main() -> i64:\n    return missing\n"
        with self.assertRaisesRegex(CompileError, "unknown variable 'missing'"):
            compile_source(source)

    def test_rejects_duplicate_variable(self):
        source = "fn main() -> i64:\n    let value = 1\n    let value = 2\n    return value\n"
        with self.assertRaisesRegex(CompileError, "already defined"):
            compile_source(source)

    def test_rejects_assignment_to_immutable_variable(self):
        source = "fn main() -> i64:\n    let value = 1\n    set value = 2\n    return value\n"
        with self.assertRaisesRegex(CompileError, "cannot assign to immutable"):
            compile_source(source)

    def test_rejects_wrong_function_arity(self):
        source = "fn main() -> i64:\n    return twice()\nfn twice(value: i64) -> i64:\n    return value * 2\n"
        with self.assertRaisesRegex(CompileError, "expects 1 arguments"):
            compile_source(source)


if __name__ == "__main__":
    unittest.main()