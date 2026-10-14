"""Scanner tests. Misattributing a trace link is worse than missing one, so ambiguity must be an error."""
import textwrap
import unittest

from reqthread.scan import scan_file


def scan(code, language="c", role="source", path="src/x.c"):
    units, errors = scan_file(path, textwrap.dedent(code), language, role)
    return {u.symbol: u for u in units}, errors


class CAttribution(unittest.TestCase):
    def test_comment_above_function(self):
        u, e = scan("""
            /* @satisfies SSR-001
             * @implements DD-1 */
            int f(void) { return 0; }
        """)
        self.assertEqual(e, [])
        self.assertEqual((u["f"].satisfies, u["f"].implements), (["SSR-001"], ["DD-1"]))

    def test_return_type_on_its_own_line(self):
        u, e = scan("""
            // @satisfies SSR-001
            static bool
            check(const frame_t *f, int n)
            {
                return n > 0;
            }
        """)
        self.assertEqual(e, [])
        self.assertEqual(u["check"].satisfies, ["SSR-001"])
        self.assertEqual((u["check"].start, u["check"].end), (3, 7))

    def test_braces_and_tags_inside_strings_ignored(self):
        u, e = scan("""
            int f(void)
            {
                const char *s = "} @satisfies SSR-999 {";
                return 0;
            }
            int g(void) { return 1; }
        """)
        self.assertEqual(e, [])
        self.assertEqual(u["f"].satisfies, [])
        self.assertEqual(u["f"].end, 6)
        self.assertIn("g", u)

    def test_tag_inside_body_applies_to_enclosing(self):
        u, e = scan("""
            int f(void)
            {
                /* @implements DD-2 */
                return 0;
            }
        """)
        self.assertEqual(u["f"].implements, ["DD-2"])

    def test_function_pointer_parameter(self):
        u, e = scan("""
            // @satisfies SSR-001
            void each(void (*cb)(int), int n) { }
        """)
        self.assertEqual(u["each"].satisfies, ["SSR-001"])

    def test_tag_above_non_function_is_error_not_misattribution(self):
        u, e = scan("""
            /* @satisfies SSR-009 */
            int global = 3;
            int later(void) { return 0; }
        """)
        self.assertEqual(u["later"].satisfies, [])
        self.assertTrue(any("not directly above or inside a function" in x for x in e), e)

    def test_control_flow_is_not_a_function(self):
        u, _ = scan("""
            int f(int x)
            {
                if (x) {
                    while (x) { x--; }
                }
                return x;
            }
        """)
        self.assertEqual(sorted(u), ["f"])

    def test_preprocessor_lines_ignored(self):
        u, _ = scan("""
            #define WRAP(x) do { x; } while (0)
            #if defined(FOO)
            int f(void) { return 0; }
            #endif
        """)
        self.assertEqual(sorted(u), ["f"])

    def test_file_level_tags(self):
        u, e = scan("""
            /* @file
             * @infrastructure Board bring-up only;
             * no safety logic. */
            int main(void) { return 0; }
        """)
        self.assertEqual(e, [])
        self.assertEqual(u[None].infrastructure, "Board bring-up only; no safety logic.")
        self.assertIsNone(u["main"].infrastructure)

    def test_multiple_keys_and_dedup(self):
        u, _ = scan("""
            /* @satisfies SSR-002, SSR-003 SSR-002 */
            int f(void) { return 0; }
        """)
        self.assertEqual(u["f"].satisfies, ["SSR-002", "SSR-003"])

    def test_malformed_key(self):
        _, e = scan("""
            /* @satisfies ssr-1 */
            int f(void) { return 0; }
        """)
        self.assertTrue(any("not a valid key" in x for x in e), e)

    def test_empty_infrastructure_reason(self):
        _, e = scan("""
            /* @infrastructure */
            int f(void) { return 0; }
        """)
        self.assertTrue(any("needs a reason" in x for x in e), e)

    def test_verifies_in_source_rejected(self):
        _, e = scan("""
            /* @verifies SSR-001 */
            int f(void) { return 0; }
        """)
        self.assertTrue(any("not valid in a source file" in x for x in e), e)


class CTests(unittest.TestCase):
    def test_ztest_macros_and_file_inheritance(self):
        u, e = scan("""
            /* @file @verifies SSR-001 */
            #include <zephyr/ztest.h>
            ZTEST(hb, test_trip)
            {
                zassert_true(1);
            }
            /* @verifies SSR-002 */
            ZTEST_F(hb, test_auth) { }
            static void helper(void) { }
        """, role="test", path="tests/t.c")
        self.assertEqual(e, [])
        self.assertEqual(sorted(u), ["hb.test_auth", "hb.test_trip"])
        self.assertEqual(u["hb.test_auth"].verifies, ["SSR-001", "SSR-002"])

    def test_unity_style_test_functions(self):
        u, _ = scan("""
            /* @verifies SSR-001 */
            void test_timeout(void) { }
            void setUp(void) { }
        """, role="test", path="tests/t.c")
        self.assertEqual(sorted(u), ["test_timeout"])

    def test_satisfies_in_test_rejected(self):
        _, e = scan("""
            /* @satisfies SSR-001 */
            void test_x(void) { }
        """, role="test", path="tests/t.c")
        self.assertTrue(any("not valid in a test file" in x for x in e), e)


class Python(unittest.TestCase):
    def test_docstring_comment_decorator_and_class(self):
        u, e = scan('''
            """Module docstring."""
            import pytest

            def test_a():
                """@verifies SSR-001"""

            # @verifies SSR-002
            @pytest.mark.slow
            def test_b():
                pass

            class TestThing:
                """@verifies SSR-003"""
                def test_c(self):
                    pass
                def test_d(self):
                    """@verifies SSR-004"""
        ''', language="python", role="test", path="tests/test_x.py")
        self.assertEqual(e, [])
        self.assertEqual(u["test_a"].verifies, ["SSR-001"])
        self.assertEqual(u["test_b"].verifies, ["SSR-002"])
        self.assertEqual(u["TestThing.test_c"].verifies, ["SSR-003"])
        self.assertEqual(u["TestThing.test_d"].verifies, ["SSR-003", "SSR-004"])

    def test_annotation_on_non_test_is_error(self):
        _, e = scan('''
            def helper():
                """@verifies SSR-001"""
        ''', language="python", role="test", path="tests/test_x.py")
        self.assertTrue(any("not a test" in x for x in e), e)

    def test_module_docstring_without_file_is_error(self):
        _, e = scan('''
            """@verifies SSR-001"""
            import os

            def test_a():
                pass
        ''', language="python", role="test", path="tests/test_x.py")
        self.assertTrue(any("add @file" in x for x in e), e)

    def test_source_functions_and_methods_are_units(self):
        u, e = scan('''
            # @satisfies SSR-001
            def supervise():
                pass

            class Link:
                """@implements DD-1"""
                def send(self):
                    pass
        ''', language="python", role="source", path="src/link.py")
        self.assertEqual(e, [])
        self.assertEqual(u["supervise"].satisfies, ["SSR-001"])
        self.assertEqual(u["Link.send"].implements, ["DD-1"])

    def test_infrastructure_reason_stops_at_blank_line(self):
        u, _ = scan('''
            def f():
                """Helper.

                @infrastructure Logging shim with no
                safety role.

                Unrelated docstring text.
                """
        ''', language="python", role="source", path="src/x.py")
        self.assertEqual(u["f"].infrastructure, "Logging shim with no safety role.")

    def test_syntax_error_reported(self):
        _, e = scan("def broken(:\n", language="python", role="source", path="src/x.py")
        self.assertTrue(any("cannot parse" in x for x in e), e)


if __name__ == "__main__":
    unittest.main()
