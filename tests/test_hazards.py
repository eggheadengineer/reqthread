"""Hazard analysis: item files, links, gate rules 11-13, and the standalone `hazards` command."""
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

from reqthread.build import build
from reqthread.gates import evaluate

ROOT = pathlib.Path(__file__).resolve().parent.parent
NOW = "2026-10-15T12:00:00Z"
COMMIT = "b" * 40


class Workspace:
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

    def write(self, rel, text):
        p = self.proj / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def edit(self, rel, old, new):
        p = self.proj / rel
        text = p.read_text()
        assert old in text, (rel, old)
        p.write_text(text.replace(old, new))

    def build(self):
        return build(self.config, now=NOW, commit=COMMIT)


def gap_ids(res):
    assert res.errors == [], res.errors
    return {g.id for g in evaluate(res.bundle)}


def cli(*args):
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    return subprocess.run([sys.executable, "-m", "reqthread", *args], capture_output=True, text=True, env=env)


class ReferenceProject(unittest.TestCase):
    def test_hazard_chain_builds_and_only_fm001_is_unmitigated(self):
        with Workspace() as w:
            res = w.build()
            b = res.bundle
            kinds = {e["kind"] for e in b["entities"]}
            self.assertIn("hazard", kinds)
            self.assertIn("cause", kinds)
            links = {(l["type"], l["from"], l["to"]) for l in b["links"]}
            self.assertIn(("mitigates", "req:SSR-003", "cause:UCA-003"), links)
            self.assertIn(("leads_to", "cause:FM-001", "haz:HAZ-001"), links)
            self.assertIn(("located_in", "cause:UCA-001", "arch:ARCH-RX"), links)
            gaps = gap_ids(res)
            self.assertIn("rule12:cause:FM-001:unmitigated", gaps)
            self.assertNotIn("rule11:haz:HAZ-001:unmitigated", gaps)   # mitigated through its other causes

    def test_bundle_format_is_0_2(self):
        with Workspace() as w:
            self.assertEqual(w.build().bundle["bundle_format"], "0.2.0")


class Rules(unittest.TestCase):
    def test_rule12_clears_with_accepted_risk(self):
        with Workspace() as w:
            w.edit("causes/FM-001.cause.md", "status: approved\n",
                   "accepted:\n  justification: Output driver is a certified SIL 3 relay module; failure covered by hardware FMEDA.\n  approved_by: reviewer-a\n  approved_at: 2026-10-13T15:00:00Z\nstatus: approved\n")
            self.assertNotIn("rule12:cause:FM-001:unmitigated", gap_ids(w.build()))

    def test_rule12_clears_with_mitigating_requirement(self):
        with Workspace() as w:
            w.edit("requirements/SSR-001.req.md", "mitigates: [UCA-001]\n", "mitigates: [UCA-001, FM-001]\n")
            self.assertNotIn("rule12:cause:FM-001:unmitigated", gap_ids(w.build()))

    def test_rule11_fires_for_hazard_with_only_unmitigated_causes(self):
        with Workspace() as w:
            w.write("hazards/HAZ-002.hazard.md", "---\nid: HAZ-002\nstatus: approved\n---\n# Operator misled by stale status LED\n\nThe status LED shows a live link after the link has dropped.\n")
            w.write("causes/UCA-009.cause.md", "---\nid: UCA-009\ntype: uca\nhazards: [HAZ-002]\nstatus: approved\n---\n# LED update skipped on timeout path\n")
            gaps = gap_ids(w.build())
            self.assertIn("rule11:haz:HAZ-002:unmitigated", gaps)
            self.assertIn("rule12:cause:UCA-009:unmitigated", gaps)

    def test_rule11_direct_mitigation_counts(self):
        with Workspace() as w:
            w.write("hazards/HAZ-002.hazard.md", "---\nid: HAZ-002\nstatus: approved\n---\n# Operator misled by stale status LED\n\nText.\n")
            w.edit("requirements/SSR-001.req.md", "mitigates: [UCA-001]\n", "mitigates: [UCA-001, HAZ-002]\n")
            self.assertNotIn("rule11:haz:HAZ-002:unmitigated", gap_ids(w.build()))

    def test_rule13_mitigating_requirement_needs_integrity_level(self):
        with Workspace() as w:
            w.edit("requirements/SSR-002.req.md", "integrity_level: SIL3\n", "")
            self.assertIn("rule13:req:SSR-002:integrity", gap_ids(w.build()))

    def test_retired_cause_is_ignored(self):
        with Workspace() as w:
            w.edit("causes/FM-001.cause.md", "status: approved\n", "status: retired\n")
            self.assertNotIn("rule12:cause:FM-001:unmitigated", gap_ids(w.build()))


class FileErrors(unittest.TestCase):
    def test_unknown_front_matter_key_is_rejected(self):
        with Workspace() as w:
            w.edit("requirements/SSR-001.req.md", "mitigates: [UCA-001]\n", "mitigate: [UCA-001]\n")
            res = w.build()
            self.assertTrue(any("mitigate" in e and "unexpected" in e.lower() or "additional properties" in e.lower() for e in res.errors), res.errors)

    def test_unknown_hazard_in_cause_is_a_build_error(self):
        with Workspace() as w:
            w.edit("causes/UCA-001.cause.md", "hazards: [HAZ-001]", "hazards: [HAZ-404]")
            res = w.build()
            self.assertTrue(any("unknown hazard HAZ-404" in e for e in res.errors), res.errors)

    def test_unknown_mitigates_target_is_a_build_error(self):
        with Workspace() as w:
            w.edit("requirements/SSR-001.req.md", "mitigates: [UCA-001]", "mitigates: [UCA-404]")
            res = w.build()
            self.assertTrue(any("unknown hazard or cause UCA-404" in e for e in res.errors), res.errors)

    def test_accepted_by_unknown_person_is_a_build_error(self):
        with Workspace() as w:
            w.edit("causes/FM-001.cause.md", "status: approved\n",
                   "accepted:\n  justification: covered elsewhere\n  approved_by: nobody\n  approved_at: 2026-10-13T15:00:00Z\nstatus: approved\n")
            res = w.build()
            self.assertTrue(any("accepted.approved_by 'nobody' is not in people" in e for e in res.errors), res.errors)

    def test_hazard_without_text_is_rejected(self):
        with Workspace() as w:
            w.write("hazards/HAZ-003.hazard.md", "---\nid: HAZ-003\nstatus: draft\n---\n# Title only\n")
            res = w.build()
            self.assertTrue(any("no hazard text" in e for e in res.errors), res.errors)


class StandaloneCommand(unittest.TestCase):
    def test_hazards_command_on_reference_project(self):
        ref = ROOT / "examples" / "wb55-ref"
        r = cli("hazards", "--hazards", str(ref / "hazards"), "--causes", str(ref / "causes"), "--requirements", str(ref / "requirements"))
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("FM-001", r.stdout)
        self.assertIn("UNMITIGATED", r.stdout)
        self.assertIn("UCA-003  Receiver accepts a replayed heartbeat  <- SSR-003", r.stdout)
        self.assertIn("1 unmitigated", r.stdout)

    def test_hazards_command_without_requirements(self):
        ref = ROOT / "examples" / "wb55-ref"
        r = cli("hazards", "--hazards", str(ref / "hazards"), "--causes", str(ref / "causes"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("4 unmitigated", r.stdout)   # nothing can be mitigated without requirement files


if __name__ == "__main__":
    unittest.main()
