"""Negative and positive tests for the formats and validator.

reqthread is a T2 tool: a check that silently passes bad input could let a
defect go unrevealed. Every rule the validator enforces gets a test proving it
rejects what it should.
"""
import copy
import json
import pathlib
import shutil
import tempfile
import unittest

import yaml

from reqthread import formats as V
from reqthread.gates import evaluate

ROOT = pathlib.Path(__file__).resolve().parent.parent

STD = ROOT / "standards" / "iec61508-3.skeleton.yaml"
REF = ROOT / "examples" / "reference"
BUNDLE = json.loads((REF / "bundle.json").read_text())
STD_DATA, _ = V.check_standard(STD)


def entity(b, eid):
    return next(e for e in b["entities"] if e["id"] == eid)


def full_check(b, root=REF):
    errs = V.check_bundle_schema(b)
    if errs:
        return errs, []
    errs = V.check_references(b, STD_DATA, STD, root)
    return errs, ([] if errs else [f"rule {g.rule}: {g.message}" for g in evaluate(b)])


class Baseline(unittest.TestCase):
    def test_reference_example_valid_with_exactly_one_known_gap(self):
        errs, gaps = full_check(copy.deepcopy(BUNDLE))
        self.assertEqual(errs, [])
        self.assertEqual(gaps, ["rule 1: SSR-003 has no verifying test at level 'module'"])

    def test_standards_valid(self):
        for f in ("iec61508-3.skeleton.yaml", "demo-std.yaml"):
            self.assertEqual(V.check_standard(ROOT / "standards" / f)[1], [], f)

    def test_requirement_files_valid(self):
        self.assertEqual(V.check_requirement_files(REF / "requirements")[0], [])


class SchemaRejects(unittest.TestCase):
    def assertSchemaError(self, b, needle):
        errs = V.check_bundle_schema(b)
        self.assertTrue(any(needle in e for e in errs), errs)

    def test_unknown_property_on_entity(self):
        b = copy.deepcopy(BUNDLE)
        entity(b, "req:SSR-001")["priority"] = "high"
        self.assertSchemaError(b, "priority")

    def test_id_prefix_must_match_kind(self):
        b = copy.deepcopy(BUNDLE)
        entity(b, "req:SSR-001")["id"] = "code:SSR-001"
        self.assertSchemaError(b, "does not match")

    def test_unknown_kind(self):
        b = copy.deepcopy(BUNDLE)
        b["entities"].append({"id": "widget:x", "kind": "widget"})
        self.assertSchemaError(b, "unknown kind")

    def test_bad_hash_format(self):
        b = copy.deepcopy(BUNDLE)
        b["artifacts"][0]["hash"] = "md5:abc"
        self.assertSchemaError(b, "does not match")

    def test_unknown_top_level_property(self):
        b = copy.deepcopy(BUNDLE)
        b["signature"] = "x"
        self.assertSchemaError(b, "signature")


class ReferencesReject(unittest.TestCase):
    def assertRefError(self, b, needle, root=REF):
        errs, _ = full_check(b, root)
        self.assertTrue(any(needle in e for e in errs), errs)

    def test_dangling_link(self):
        b = copy.deepcopy(BUNDLE)
        b["links"].append({"type": "verifies", "from": "test:nope", "to": "req:SSR-003"})
        self.assertRefError(b, "unknown entity test:nope")

    def test_disallowed_link_pair(self):
        b = copy.deepcopy(BUNDLE)
        b["links"].append({"type": "verifies", "from": "code:src/frame_auth.c#seq_check", "to": "req:SSR-003"})
        self.assertRefError(b, "verifies not allowed from code_unit")

    def test_field_reference_wrong_kind(self):
        b = copy.deepcopy(BUNDLE)
        entity(b, "result:1")["test"] = "test:missing"
        self.assertRefError(b, "expected an existing test_case")

    def test_duplicate_id(self):
        b = copy.deepcopy(BUNDLE)
        b["entities"].append(copy.deepcopy(entity(b, "arch:ARCH-RX")))
        self.assertRefError(b, "duplicate entity id")

    def test_unknown_test_level(self):
        b = copy.deepcopy(BUNDLE)
        entity(b, "req:SSR-002")["test_levels"] = ["unit"]
        self.assertRefError(b, "unknown test level 'unit'")

    def test_unknown_tool_class(self):
        b = copy.deepcopy(BUNDLE)
        entity(b, "tool:gcovr")["class"] = "T9"
        self.assertRefError(b, "unknown tool class")

    def test_standard_hash_mismatch(self):
        b = copy.deepcopy(BUNDLE)
        b["project"]["standard"]["data_hash"] = "sha256:" + "0" * 64
        self.assertRefError(b, "data_hash does not match")

    def test_tampered_artifact(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d) / "reference"
            shutil.copytree(REF, root)
            p = root / "requirements" / "SSR-001.req.md"
            p.write_text(p.read_text().replace("300 ms", "3000 ms"))
            self.assertRefError(copy.deepcopy(BUNDLE), "SSR-001.req.md: hash mismatch", root)

    def test_bundle_title_drift_from_source_file(self):
        b = copy.deepcopy(BUNDLE)
        entity(b, "req:SSR-001")["title"] = "Something else"
        self.assertRefError(b, "title differs from source file")


class GateRulesFire(unittest.TestCase):
    def gaps(self, b):
        errs, gaps = full_check(b)
        self.assertEqual(errs, [])
        return gaps

    def test_rule1_closing_the_gap_clears_it(self):
        b = copy.deepcopy(BUNDLE)
        b["entities"].append({"id": "test:tests/auth/test_seq.c::test_replay_rejected", "kind": "test_case",
                              "name": "tests/auth/test_seq.c::test_replay_rejected", "level": "module"})
        b["links"].append({"type": "verifies", "from": "test:tests/auth/test_seq.c::test_replay_rejected", "to": "req:SSR-003"})
        self.assertEqual(self.gaps(b), ["rule 4: tests/auth/test_seq.c::test_replay_rejected has no result at baseline (verifies SSR-003)"])
        b["entities"].append({"id": "result:4", "kind": "test_result", "test": "test:tests/auth/test_seq.c::test_replay_rejected",
                              "environment": "env:host-native-sim", "outcome": "pass", "run_at": "2026-10-13T17:40:00Z"})
        self.assertEqual(self.gaps(b), [])

    def test_rule4_skipped_only_is_not_verification(self):
        b = copy.deepcopy(BUNDLE)
        entity(b, "result:3")["outcome"] = "skip"
        self.assertIn("rule 4: tests/auth/test_mac.c::test_bad_mac_rejected only skipped at baseline (verifies SSR-002)", self.gaps(b))

    def test_rule1_wrong_level_does_not_count(self):
        b = copy.deepcopy(BUNDLE)
        b["links"] = [l for l in b["links"] if l["from"] != "test:tests/hil/test_link_drop.py::test_link_loss_trips"]
        self.assertIn("rule 1: SSR-001 has no verifying test at level 'pe_integration'", self.gaps(b))

    def test_rule2_orphan_ssr(self):
        b = copy.deepcopy(BUNDLE)
        b["links"] = [l for l in b["links"] if not (l["from"] == "req:SSR-002" and l["type"] == "derives_from")]
        self.assertIn("rule 2: SSR-002 does not derive from a system-level requirement", self.gaps(b))

    def test_rule3_untraced_code(self):
        b = copy.deepcopy(BUNDLE)
        entity(b, "code:src/main.c#main")["infrastructure"] = None
        self.assertIn("rule 3: src/main.c#main traces to no requirement or design element", self.gaps(b))

    def test_rule4_failing_test(self):
        b = copy.deepcopy(BUNDLE)
        entity(b, "result:2")["outcome"] = "fail"
        self.assertTrue(any(g.startswith("rule 4:") for g in self.gaps(b)))

    def test_rule7_open_finding(self):
        b = copy.deepcopy(BUNDLE)
        f = next(e for e in b["entities"] if e["kind"] == "finding")
        f["state"] = "open"
        self.assertTrue(any(g.startswith("rule 7:") and "is open" in g for g in self.gaps(b)))

    def test_rule7_expired_deviation(self):
        b = copy.deepcopy(BUNDLE)
        entity(b, "dev:DEV-001")["expires_at"] = "2026-01-01"
        self.assertTrue(any("no unexpired deviation" in g for g in self.gaps(b)))


class RequirementFilesReject(unittest.TestCase):
    # Item files go through check_item_files; check_requirement_files adds derives_from resolution.
    def check(self, name, text):
        with tempfile.TemporaryDirectory() as d:
            (pathlib.Path(d) / name).write_text(text)
            return V.check_requirement_files(d)[0]

    def test_missing_front_matter(self):
        self.assertTrue(any("no YAML front matter" in e for e in self.check("SSR-9.req.md", "# Title\n")))

    def test_missing_requirement_text(self):
        errs = self.check("SSR-9.req.md", "---\nid: SSR-9\nlevel: software\ntype: functional\nstatus: draft\n---\n# T\n")
        self.assertTrue(any("no requirement text" in e for e in errs), errs)

    def test_bad_level(self):
        errs = self.check("SSR-9.req.md", "---\nid: SSR-9\nlevel: hardware\ntype: functional\nstatus: draft\n---\n# T\n\nText.\n")
        self.assertTrue(any("hardware" in e for e in errs), errs)

    def test_filename_must_match_id(self):
        errs = self.check("wrong.req.md", "---\nid: SSR-9\nlevel: software\ntype: functional\nstatus: draft\n---\n# T\n")
        self.assertTrue(any("should be SSR-9.req.md" in e for e in errs), errs)

    def test_dangling_derives_from(self):
        errs = self.check("SSR-9.req.md", "---\nid: SSR-9\nlevel: software\ntype: functional\nstatus: draft\nderives_from: [SYS-1]\n---\n# T\n")
        self.assertTrue(any("unknown requirement SYS-1" in e for e in errs), errs)


class StandardDataRejects(unittest.TestCase):
    def test_unknown_recommendation_code(self):
        data = yaml.safe_load((ROOT / "standards" / "demo-std.yaml").read_text())
        data["techniques"][0]["levels"]["L3"] = "SUPER"
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            yaml.safe_dump(data, f)
        try:
            self.assertTrue(any("unknown recommendation code" in e for e in V.check_standard(f.name)[1]))
        finally:
            pathlib.Path(f.name).unlink()


if __name__ == "__main__":
    unittest.main()
