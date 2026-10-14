#!/usr/bin/env python3
"""Guard AST interpretation and sampled-profile accounting."""
import unittest
from native_decode_ast import ast_command, inventory
from native_decode_profile import leaves


class AuditTest(unittest.TestCase):
    def test_ast_flags_keep_defines_but_do_not_write_build_outputs(self):
        result = ast_command('clang -DARM_NEON -I"a b" -O3 -MD -MT obj -MF deps -o obj -c source.c')
        self.assertEqual(result, ['clang', '-DARM_NEON', '-Ia b', '-O3', 'source.c',
                                  '-fsyntax-only', '-Xclang', '-ast-dump=json'])

    def test_macro_expansion_location_and_indirect_calls_are_preserved(self):
        reference = {'kind': 'DeclRefExpr', 'referencedDecl': {'kind': 'FunctionDecl', 'name': 'chunkcopy_neon'}}
        pointer = {'kind': 'DeclRefExpr', 'referencedDecl': {'kind': 'VarDecl', 'name': 'dispatch'}}
        function = {'kind': 'FunctionDecl', 'name': 'inflate_fast_neon',
                    'loc': {'expansionLoc': {'file': 'inffast_tpl.h', 'line': 53}},
                    'inner': [{'kind': 'CompoundStmt', 'inner': [
                        {'kind': 'CallExpr', 'inner': [reference]},
                        {'kind': 'CallExpr', 'inner': [pointer]},
                        {'kind': 'DeclRefExpr', 'referencedDecl': {'kind': 'FunctionDecl', 'name': 'crc32_armv8'}},
                    ]}]}
        row, = inventory(function)
        self.assertEqual(row['location']['expansionLoc']['file'], 'inffast_tpl.h')
        self.assertEqual(row['direct_call_sites'], {'chunkcopy_neon': 1})
        self.assertEqual(row['indirect_call_sites'], 1)
        self.assertEqual(row['function_references'], ['chunkcopy_neon', 'crc32_armv8'])

    def test_profile_denominator_includes_omitted_small_leaf_counts(self):
        text = '''Call graph:
    100 Thread_1
Sort by top of stack, same collapsed (when >= 5):
        decoder (in worker)        90
        crc (in worker)        5
Binary Images:
'''
        total, rows = leaves(text)
        self.assertEqual(total, 100)
        self.assertEqual(sum(r['samples'] for r in rows), 95)

    def test_multiple_threads_require_explicit_accounting(self):
        with self.assertRaisesRegex(ValueError, 'one sampled'):
            leaves(' 10 Thread_1\n 20 Thread_2\nSort by top of stack, same collapsed\n f 30\nBinary Images:')


if __name__ == '__main__':
    unittest.main()
