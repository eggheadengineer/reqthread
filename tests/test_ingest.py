"""Parser tests, against the real tool outputs in examples/wb55-ref/ci-out plus small edge-case inputs."""
import json
import pathlib
import tempfile
import textwrap
import unittest

from reqthread.ingest import (
    match_junit, normalize_path, parse_cobertura, parse_junit, parse_lcov, parse_sarif, unit_metrics,
)

ROOT = pathlib.Path(__file__).resolve().parent.parent
REF = ROOT / "examples" / "wb55-ref"
CI = REF / "ci-out"
# The committed coverage fixtures carry absolute paths from the machine that generated them, exactly as a
# CI artifact from another checkout would. Parsers resolve those by suffix against known source files.
KNOWN = ["src/frame_auth.c", "src/supervisor.c", "src/main.c"]


def tmpfile(text, suffix):
    f = tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False)
    f.write(textwrap.dedent(text))
    f.close()
    return f.name


class Paths(unittest.TestCase):
    def test_absolute_inside_root(self):
        self.assertEqual(normalize_path(f"{REF.resolve()}/src/a.c", REF), "src/a.c")

    def test_absolute_elsewhere_matched_by_suffix(self):
        self.assertEqual(normalize_path("/builds/x/src/a.c", REF, ["src/a.c"]), "src/a.c")

    def test_outside_repo(self):
        self.assertIsNone(normalize_path("/usr/include/stdio.h", REF))
        self.assertIsNone(normalize_path("../other/a.c", REF))

    def test_relative_and_uri(self):
        self.assertEqual(normalize_path("./src/a.c", REF), "src/a.c")
        self.assertEqual(normalize_path(f"file://{REF.resolve()}/src/a.c", REF), "src/a.c")


class Junit(unittest.TestCase):
    def test_real_pytest_output(self):
        cases = parse_junit(CI / "junit-module.xml")
        self.assertEqual(len(cases), 6)
        outcomes = {c.name: c.outcome for c in cases}
        self.assertEqual(outcomes["test_link_loss_trips"], "skip")
        self.assertEqual(outcomes["test_trip_after_300ms"], "pass")
        self.assertTrue(all(c.timestamp and c.timestamp.endswith("Z") for c in cases))

    def test_outcomes_and_matching(self):
        path = tmpfile("""
            <testsuites><testsuite name="s" timestamp="2026-10-13T10:00:00Z">
              <testcase classname="tests.test_a" name="test_ok"/>
              <testcase classname="tests.test_a" name="test_bad"><failure message="x"/></testcase>
              <testcase classname="tests.test_a" name="test_err"><error message="x"/></testcase>
              <testcase classname="tests.test_a" name="test_param[1]"/>
              <testcase classname="tests.test_a" name="test_param[2]"><failure/></testcase>
              <testcase classname="hb" name="test_trip"/>
              <testcase classname="ghost" name="test_nobody"/>
            </testsuite></testsuites>""", ".xml")
        tests = {
            "t1": ("tests/test_a.py", "test_ok"), "t2": ("tests/test_a.py", "test_bad"),
            "t3": ("tests/test_a.py", "test_err"), "t4": ("tests/test_a.py", "test_param"),
            "t5": ("tests/t.c", "hb.test_trip"),
        }
        out, unmatched = match_junit(parse_junit(path), tests)
        self.assertEqual({k: v[0] for k, v in out.items()},
                         {"t1": "pass", "t2": "fail", "t3": "error", "t4": "fail", "t5": "pass"})
        self.assertEqual(unmatched, ["ghost.test_nobody"])

    def test_ambiguous_bare_name_is_not_guessed(self):
        path = tmpfile('<testsuite><testcase classname="x" name="test_same"/></testsuite>', ".xml")
        out, unmatched = match_junit(parse_junit(path), {"a": ("tests/a.c", "test_same"), "b": ("tests/b.c", "test_same")})
        self.assertEqual(out, {})
        self.assertEqual(len(unmatched), 1)


class Coverage(unittest.TestCase):
    def test_real_lcov(self):
        files, unmapped = parse_lcov(CI / "coverage.lcov", REF, KNOWN)
        self.assertEqual(sorted(files), ["src/frame_auth.c", "src/supervisor.c"])
        self.assertEqual(unmapped, [])
        # seq_check is lines 30-39 in src/frame_auth.c. The module tests alone left the replay branch
        # unexecuted (5/6, 1/4); the faultbench replay scenario covers it, so the fixtures now show full
        # coverage while SSR-003 still has no traced test. Coverage is not traceability.
        m = unit_metrics(files["src/frame_auth.c"], 30, 39)
        self.assertEqual(m["statement"], {"covered": 6, "total": 6})
        self.assertEqual(m["branch"], {"covered": 4, "total": 4})

    def test_real_cobertura_agrees_with_lcov(self):
        lcov, _ = parse_lcov(CI / "coverage.lcov", REF, KNOWN)
        cob, _ = parse_cobertura(CI / "coverage.xml", REF, KNOWN)
        for path in lcov:
            self.assertEqual(set(lcov[path].lines), set(cob[path].lines), path)
            for ln in lcov[path].branches:
                self.assertEqual(lcov[path].branches[ln], cob[path].branches[ln], f"{path}:{ln}")

    def test_lcov_branch_taken_dash_and_zero(self):
        path = tmpfile(f"""\
            SF:{REF.resolve()}/src/a.c
            DA:1,1
            DA:2,0
            BRDA:1,0,0,-
            BRDA:1,0,1,0
            BRDA:1,0,2,3
            end_of_record
            """, ".info")
        files, _ = parse_lcov(path, REF)
        self.assertEqual(files["src/a.c"].branches[1], (1, 3))
        self.assertEqual(unit_metrics(files["src/a.c"], 1, 2)["statement"], {"covered": 1, "total": 2})

    def test_nothing_instrumented_gives_none(self):
        path = tmpfile(f"SF:{REF.resolve()}/src/a.c\nDA:10,1\nend_of_record\n", ".info")
        files, _ = parse_lcov(path, REF)
        self.assertIsNone(unit_metrics(files["src/a.c"], 1, 5))


class Sarif(unittest.TestCase):
    def test_real_flawfinder(self):
        results, unmapped = parse_sarif(CI / "flawfinder.sarif", REF, KNOWN)
        self.assertEqual(unmapped, [])
        self.assertEqual({(r.tool, r.rule_id, r.path, r.line) for r in results},
                         {("Flawfinder", "FF1004", "src/frame_auth.c", 13), ("Flawfinder", "FF1004", "src/frame_auth.c", 14)})
        self.assertTrue(all(r.fingerprint for r in results))

    def test_suppression_and_default_level(self):
        doc = {"runs": [{"tool": {"driver": {"name": "cppcheck", "version": "2.14",
                                             "rules": [{"id": "r1", "defaultConfiguration": {"level": "error"}}]}},
                         "results": [{"ruleId": "r1", "message": {"text": "m"},
                                      "locations": [{"physicalLocation": {"artifactLocation": {"uri": "src/a.c"}, "region": {"startLine": 3}}}],
                                      "suppressions": [{"kind": "inSource"}]},
                                     {"ruleId": "r1", "locations": [{"physicalLocation": {"artifactLocation": {"uri": "/usr/include/x.h"}}}]}]}]}
        path = tmpfile(json.dumps(doc), ".sarif")
        results, unmapped = parse_sarif(path, REF)
        self.assertEqual(len(results), 1)
        self.assertEqual((results[0].level, results[0].suppressed_in_source), ("error", True))
        self.assertEqual(unmapped, ["/usr/include/x.h"])


if __name__ == "__main__":
    unittest.main()
