"""End-to-end tests: build the WB55 reference project, gate it, ratchet it, and drive the CLI."""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

from reqthread.build import build
from reqthread.formats import canonical_hash
from reqthread.gates import evaluate, ratchet
from reqthread.report import render

ROOT = pathlib.Path(__file__).resolve().parent.parent
NOW = "2026-10-13T20:00:00Z"
COMMIT = "a" * 40
EXPECTED_GAPS = {
    "rule1:req:SSR-003:module",
    "rule4:test:tests/hil/test_link_drop.py::test_link_loss_trips:not-passed",
}


class Workspace:
    """A throwaway copy of the reference project (and the standards it points at)."""

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = pathlib.Path(self.tmp.name)
        shutil.copytree(ROOT / "standards", base / "standards")
        shutil.copytree(ROOT / "examples" / "wb55-ref", base / "examples" / "wb55-ref",
                        ignore=shutil.ignore_patterns("build", "__pycache__"))
        self.proj = base / "examples" / "wb55-ref"
        self.config = self.proj / "reqthread.yaml"
        return self

    def __exit__(self, *exc):
        self.tmp.cleanup()

    def edit(self, rel, old, new):
        p = self.proj / rel
        text = p.read_text()
        assert old in text, (rel, old)
        p.write_text(text.replace(old, new))

    def build(self, **kw):
        return build(self.config, now=NOW, commit=COMMIT, **kw)


def cli(*args, cwd=None):
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    return subprocess.run([sys.executable, "-m", "reqthread", *args], capture_output=True, text=True, env=env, cwd=cwd)


class Build(unittest.TestCase):
    def test_reference_project_builds_with_exactly_the_expected_gaps(self):
        with Workspace() as w:
            res = w.build()
            self.assertEqual(res.errors, [])
            self.assertEqual({g.id for g in evaluate(res.bundle)}, EXPECTED_GAPS)

    def test_build_is_deterministic(self):
        with Workspace() as w:
            self.assertEqual(canonical_hash(w.build().bundle), canonical_hash(w.build().bundle))

    def test_previous_bundle_is_chained(self):
        with Workspace() as w:
            first = w.build().bundle
            second = w.build(previous=first).bundle
            self.assertIsNone(first["baseline"]["previous_bundle_hash"])
            self.assertEqual(second["baseline"]["previous_bundle_hash"], canonical_hash(first))

    def test_deviation_covers_both_real_findings(self):
        with Workspace() as w:
            b = w.build().bundle
            findings = [e for e in b["entities"] if e["kind"] == "finding"]
            self.assertEqual(len(findings), 2)
            self.assertTrue(all(f["state"] == "deviated" for f in findings))

    def test_removing_the_deviation_opens_rule_7(self):
        with Workspace() as w:
            (w.proj / "deviations.yaml").write_text("[]\n")
            res = w.build()
            self.assertEqual(sum(g.rule == 7 for g in evaluate(res.bundle)), 2)
            self.assertFalse(any("stale" in x for x in res.warnings))

    def test_expired_deviation_is_a_gap(self):
        with Workspace() as w:
            w.edit("deviations.yaml", "expires_at: 2027-04-30", "expires_at: 2026-01-01")
            self.assertTrue(any(g.rule == 7 and "unexpired" in g.message for g in evaluate(w.build().bundle)))

    def test_hil_result_closes_the_rule_4_gap(self):
        with Workspace() as w:
            (w.proj / "ci-out" / "junit-hil.xml").write_text(
                '<testsuite timestamp="2026-10-13T19:00:00Z">'
                '<testcase classname="tests.hil.test_link_drop" name="test_link_loss_trips"/></testsuite>')
            gaps = {g.id for g in evaluate(w.build().bundle)}
            self.assertEqual(gaps, {"rule1:req:SSR-003:module"})

    def test_dangling_annotation_is_a_build_error(self):
        with Workspace() as w:
            w.edit("src/frame_auth.c", "@satisfies SSR-003\n", "@satisfies SSR-033\n")
            res = w.build()
            self.assertIsNone(res.bundle)
            self.assertTrue(any("unknown requirement SSR-033" in e for e in res.errors), res.errors)

    def test_tampering_after_build_is_detectable(self):
        with Workspace() as w:
            from reqthread.formats import check_references
            b = w.build().bundle
            w.edit("requirements/SSR-001.req.md", "300 ms of", "3000 ms of")
            errs = check_references(b, root=w.proj)
            self.assertTrue(any("SSR-001.req.md: hash mismatch" in e for e in errs), errs)

    def test_unknown_environment_is_an_error(self):
        with Workspace() as w:
            w.edit("reqthread.yaml", "environment: host, section: 07_module_testing }\n  - { type: junit",
                   "environment: nowhere, section: 07_module_testing }\n  - { type: junit")
            self.assertTrue(any("unknown environment 'nowhere'" in e for e in w.build().errors))

    def test_unknown_test_level_rejected_against_standard(self):
        with Workspace() as w:
            w.edit("reqthread.yaml", "level: module }", "level: unit }")
            self.assertTrue(any("unknown test level 'unit'" in e for e in w.build().errors))

    def test_file_in_both_source_and_test_globs(self):
        with Workspace() as w:
            w.edit("reqthread.yaml", '- { glob: "src/**/*.h", language: c }',
                   '- { glob: "src/**/*.h", language: c }\n  - { glob: "tests/hil/*.py", language: python }')
            self.assertTrue(any("matched by both" in e for e in w.build().errors))


class Ratchet(unittest.TestCase):
    def test_new_gap_is_separated_from_baseline_gaps(self):
        with Workspace() as w:
            baseline = w.build().bundle
            w.edit("tests/module/test_frame_auth.py", '"""@verifies SSR-002"""\n    a = Auth(key=0x1234)\n    f =',
                   '"""Bad MAC."""\n    a = Auth(key=0x1234)\n    f =')
            w.edit("tests/module/test_frame_auth.py", 'def test_valid_frame_accepted(lib):\n    """@verifies SSR-002"""',
                   'def test_valid_frame_accepted(lib):\n    """Valid frame."""')
            new, existing, fixed = ratchet(evaluate(w.build().bundle), evaluate(baseline))
            self.assertEqual([g.id for g in new], ["rule1:req:SSR-002:module"])
            self.assertEqual({g.id for g in existing}, EXPECTED_GAPS)
            self.assertEqual(fixed, [])


class Report(unittest.TestCase):
    def test_html_escapes_content(self):
        with Workspace() as w:
            w.edit("requirements/SSR-002.req.md", "# Reject unauthenticated frames", "# Reject <script>alert(1)</script> frames")
            b = w.build().bundle
            html = render(b, evaluate(b))
            self.assertNotIn("<script>alert", html)
            self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)

    def test_report_agrees_with_gate_on_file_level_trace(self):
        with Workspace() as w:
            b = w.build().bundle
            html = render(b, evaluate(b))
            self.assertIn("via file", html)
            self.assertNotIn("untraced", html)


class Cli(unittest.TestCase):
    def test_check_exit_codes_and_outputs(self):
        with Workspace() as w:
            out = w.proj / "out"
            r = cli("check", "-c", str(w.config), "--commit", COMMIT, "-o", str(out / "b.json"),
                    "--html", str(out / "r.html"), "--json", str(out / "g.json"))
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertIn("FAIL: 2 gap(s)", r.stdout)
            gaps = json.loads((out / "g.json").read_text())
            self.assertEqual({g["id"] for g in gaps["gaps"]}, EXPECTED_GAPS)
            self.assertTrue((out / "r.html").read_text().startswith("<!doctype html>"))

            r = cli("check", "-c", str(w.config), "--commit", COMMIT, "--baseline", str(out / "b.json"))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("0 new", r.stdout)

    def test_check_existing_bundle_and_report(self):
        with Workspace() as w:
            b = w.proj / "b.json"
            self.assertEqual(cli("build", "-c", str(w.config), "--commit", COMMIT, "-o", str(b)).returncode, 0)
            self.assertEqual(cli("check", "--bundle", str(b), "--root", str(w.proj)).returncode, 2)
            r = cli("report", "--bundle", str(b), "-o", str(w.proj / "r.html"))
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_build_error_exits_1(self):
        with Workspace() as w:
            w.edit("src/frame_auth.c", "@implements DD-AUTH */\nbool frame_verify", "@implements DD-NOPE */\nbool frame_verify")
            r = cli("check", "-c", str(w.config), "--commit", COMMIT)
            self.assertEqual(r.returncode, 1)
            self.assertIn("unknown design element or architecture element DD-NOPE", r.stderr)

    def test_missing_config_exits_1(self):
        r = cli("check", "-c", "/nonexistent/reqthread.yaml")
        self.assertEqual(r.returncode, 1)
        self.assertIn("config not found", r.stderr)


if __name__ == "__main__":
    unittest.main()
