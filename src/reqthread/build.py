"""Assemble an evidence bundle from a project configuration."""
import datetime as dt
import os
import pathlib
import re
import subprocess
from dataclasses import dataclass, field

from . import GENERATOR, __version__
from .formats import (
    PREFIX, FormatError, StandardIndex, canonical_hash, check_bundle_schema, check_item_files,
    check_references, check_standard, file_hash, load_schema, load_yaml, schema_errors,
)
from .ingest import (
    OUTCOME_RANK, FileCoverage, match_junit, parse_cobertura, parse_junit, parse_lcov, parse_sarif, unit_metrics,
)
from .scan import scan_file

KIND_ORDER = {k: i for i, k in enumerate(PREFIX)}
LANG = {"c": "c", "cpp": "cpp", "python": "python"}


@dataclass
class BuildResult:
    bundle: dict | None
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    root: pathlib.Path | None = None
    standard: StandardIndex | None = None
    standard_path: pathlib.Path | None = None


def load_config(path):
    path = pathlib.Path(path)
    cfg = load_yaml(path, "config")
    return cfg, schema_errors(load_schema("config.schema.json"), cfg, f"config {path}")


def _git(root, *args):
    try:
        out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else None


def _now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _slug(s):
    return re.sub(r"[^a-z0-9._-]+", "-", s.lower()).strip("-") or "tool"


def _rel(root, p):
    try:
        return pathlib.Path(p).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


class _Builder:
    def __init__(self, config_path, now):
        self.config_path = pathlib.Path(config_path)
        self.root = self.config_path.resolve().parent
        self.now = now or _now()
        self.errors, self.warnings = [], []
        self.entities, self.links, self.artifacts = {}, set(), {}
        self.keys = {}          # human key -> entity id, for requirements, architecture, design

    # -- helpers
    def add(self, ent):
        if ent["id"] in self.entities:
            self.errors.append(f"duplicate entity {ent['id']}")
            return
        self.entities[ent["id"]] = ent

    def link(self, typ, frm, to, declared_at=None):
        self.links.add((typ, frm, to, tuple(sorted(declared_at.items())) if declared_at else None))

    def artifact(self, path, section, media_type, description=None):
        rel = _rel(self.root, path)
        if rel is None:
            self.errors.append(f"{path}: outside the project root {self.root}")
            return
        a = {"path": rel, "hash": file_hash(path), "media_type": media_type, "section": section}
        if description:
            a["description"] = description
        self.artifacts[rel] = a

    def resolve(self, key, kinds, where):
        for prefix in kinds:
            eid = self.keys.get((prefix, key))
            if eid:
                return eid
        what = " or ".join({"req": "requirement", "arch": "architecture element", "design": "design element"}[k] for k in kinds)
        self.errors.append(f"{where}: unknown {what} {key}")
        return None

    # -- stages
    def items(self, cfg):
        reqs, archs, designs = {}, {}, {}
        for section_key, suffix, store in (("requirements", ".req.md", reqs), ("architecture", ".arch.md", archs),
                                           ("design", ".design.md", designs)):
            spec = cfg.get(section_key)
            if not spec:
                continue
            for d in spec["paths"]:
                directory = self.root / d
                if not directory.is_dir():
                    self.errors.append(f"config: {section_key} path {d} is not a directory")
                    continue
                errs, items = check_item_files(directory, suffix)
                self.errors += errs
                for key, item in items.items():
                    if key in reqs or key in archs or key in designs:
                        self.errors.append(f"{item[0]}: id {key} is already used by another item")
                        continue
                    store[key] = item
                    self.artifact(item[0], spec["section"], "text/markdown")

        for key, (f, fm, title, text, rationale) in reqs.items():
            e = {"id": f"req:{key}", "kind": "requirement", "key": key, "level": fm["level"], "type": fm["type"],
                 "integrity_level": fm.get("integrity_level"), "title": title, "text": text,
                 "verification": fm.get("verification", []), "test_levels": fm.get("test_levels", []),
                 "status": fm["status"], "source": {"path": _rel(self.root, f)}}
            if rationale:
                e["rationale"] = rationale
            self.add(e)
            self.keys[("req", key)] = e["id"]
        for key, (f, fm, title, text, _r) in archs.items():
            e = {"id": f"arch:{key}", "kind": "architecture_element", "key": key, "title": title,
                 "safety_related": fm["safety_related"], "integrity_level": fm.get("integrity_level"),
                 "source": {"path": _rel(self.root, f)}}
            if text:
                e["description"] = text
            self.add(e)
            self.keys[("arch", key)] = e["id"]
        for key, (f, fm, title, text, _r) in designs.items():
            e = {"id": f"design:{key}", "kind": "design_element", "key": key, "title": title,
                 "source": {"path": _rel(self.root, f)}}
            if text:
                e["description"] = text
            self.add(e)
            self.keys[("design", key)] = e["id"]

        for key, (f, fm, *_x) in reqs.items():
            where = _rel(self.root, f)
            for typ, field_, kinds in (("derives_from", "derives_from", ["req"]), ("allocated_to", "allocated_to", ["arch"]),
                                       ("supersedes", "supersedes", ["req"])):
                for k in fm.get(field_, []):
                    to = self.resolve(k, kinds, where)
                    if to:
                        self.link(typ, f"req:{key}", to)
        for key, (f, fm, *_x) in designs.items():
            where = _rel(self.root, f)
            for k in fm.get("derives_from", []):
                to = self.resolve(k, ["arch"], where)
                if to:
                    self.link("derives_from", f"design:{key}", to)
            for k in fm.get("satisfies", []):
                to = self.resolve(k, ["req"], where)
                if to:
                    self.link("satisfies", f"design:{key}", to)

    def code(self, cfg):
        self.unit_ranges = {}     # path -> [(start, end, code_id)] for function-level units
        self.tests = {}           # test id -> (path, symbol)
        claimed = {}
        for role, globs in (("source", cfg.get("sources", [])), ("test", cfg.get("tests", []))):
            for g in globs:
                matched = sorted(p for p in self.root.glob(g["glob"]) if p.is_file())
                if not matched:
                    self.warnings.append(f"config: {role} glob {g['glob']!r} matches no files")
                for p in matched:
                    rel = _rel(self.root, p)
                    if rel in claimed:
                        if claimed[rel] != role:
                            self.errors.append(f"{rel}: matched by both a source glob and a test glob")
                        continue
                    claimed[rel] = role
                    units, errs = scan_file(rel, p.read_text(errors="replace"), g["language"], role)
                    self.errors += errs
                    if role == "source":
                        self._code_units(rel, g["language"], units)
                    else:
                        self._test_cases(rel, g["level"], units)

    def _code_units(self, rel, language, units):
        for u in units:
            cid = f"code:{rel}#{u.symbol}" if u.symbol else f"code:{rel}"
            self.add({"id": cid, "kind": "code_unit", "path": rel, "symbol": u.symbol, "language": LANG[language],
                      "infrastructure": {"reason": u.infrastructure} if u.infrastructure else None,
                      "source": {"path": rel, "line": u.start}})
            if u.symbol:
                self.unit_ranges.setdefault(rel, []).append((u.start, u.end, cid))
            for k in u.satisfies:
                to = self.resolve(k, ["req"], f"{rel}:{u.tag_lines[('satisfies', k)]}")
                if to:
                    self.link("satisfies", cid, to, {"path": rel, "line": u.tag_lines[("satisfies", k)]})
            for k in u.implements:
                to = self.resolve(k, ["design", "arch"], f"{rel}:{u.tag_lines[('implements', k)]}")
                if to:
                    self.link("implements", cid, to, {"path": rel, "line": u.tag_lines[("implements", k)]})

    def _test_cases(self, rel, level, units):
        for u in units:
            tid = f"test:{rel}::{u.symbol}"
            self.add({"id": tid, "kind": "test_case", "name": f"{rel}::{u.symbol}", "level": u.test_level or level,
                      "source": {"path": rel, "line": u.start}})
            self.tests[tid] = (rel, u.symbol)
            for k in u.verifies:
                to = self.resolve(k, ["req", "design", "arch"], f"{rel}:{u.tag_lines[('verifies', k)]}")
                if to:
                    self.link("verifies", tid, to, {"path": rel, "line": u.tag_lines[("verifies", k)]})

    def people_tools(self, cfg):
        for p in cfg.get("people", []):
            self.add({"id": f"person:{p['id']}", "kind": "person", "name": p["name"], "roles": p["roles"],
                      "competence_record": p.get("competence_record")})
        self.tool_by_name = {}
        for t in cfg.get("tools", []):
            tid = f"tool:{t['id']}"
            self.add({"id": tid, "kind": "tool", "name": t["name"], "version": t["version"], "class": t["class"],
                      "evidence": t.get("evidence", [])})
            self.tool_by_name[t["name"].lower()] = tid
            self.tool_by_name[t["id"].lower()] = tid
        for p in cfg.get("preexisting", []):
            e = {"id": f"pre:{p['id']}", "kind": "preexisting_element", "name": p["name"], "version": p["version"],
                 "route": p["route"], "justification": p.get("justification", [])}
            if p.get("origin"):
                e["origin"] = p["origin"]
            self.add(e)
        self.env_ids = set()
        for env in cfg.get("environments", []):
            e = {"id": f"env:{env['id']}", "kind": "environment", "name": env["name"], "env_type": env["env_type"]}
            for opt in ("board", "description"):
                if env.get(opt):
                    e[opt] = env[opt]
            self.add(e)
            self.env_ids.add(env["id"])

    def ingest(self, cfg):
        known = sorted(self.unit_ranges)
        results = {}                      # (test id, env) -> (outcome, ts)
        coverage = {}                     # (env, level) -> {path: FileCoverage}
        sarif = []
        for i, entry in enumerate(cfg.get("ingest", [])):
            path = self.root / entry["path"]
            if not path.is_file():
                (self.warnings if entry.get("optional") else self.errors).append(
                    f"ingest[{i}]: {entry['path']} not found")
                continue
            env = entry.get("environment")
            if env is not None and env not in self.env_ids:
                self.errors.append(f"ingest[{i}]: unknown environment {env!r}")
                continue
            kind = entry["type"]
            media = {"junit": "application/xml", "cobertura": "application/xml", "lcov": "text/plain",
                     "sarif": "application/sarif+json"}[kind]
            self.artifact(path, entry["section"], media, f"{kind} input")
            try:
                if kind == "junit":
                    outcomes, unmatched = match_junit(parse_junit(path), self.tests)
                    for tid, (outcome, ts) in outcomes.items():
                        prev = results.get((tid, env))
                        if prev is None or OUTCOME_RANK[outcome] > OUTCOME_RANK[prev[0]]:
                            results[(tid, env)] = (outcome, ts)
                    for u in unmatched:
                        self.warnings.append(f"{entry['path']}: testcase {u} matches no test in the configured test globs")
                elif kind in ("lcov", "cobertura"):
                    parse = parse_lcov if kind == "lcov" else parse_cobertura
                    files, unmapped = parse(path, self.root, known)
                    bucket = coverage.setdefault((env, entry["test_level"]), {})
                    for rel, fc in files.items():
                        merged = bucket.setdefault(rel, FileCoverage({}, {}))
                        for ln, h in fc.lines.items():
                            merged.lines[ln] = max(merged.lines.get(ln, 0), h)
                        for ln, b in fc.branches.items():
                            merged.branches[ln] = max(merged.branches.get(ln, (0, 0)), b)
                    if unmapped:
                        self.warnings.append(f"{entry['path']}: {len(unmapped)} file(s) outside the project ignored")
                else:
                    found, unmapped = parse_sarif(path, self.root, known)
                    sarif += found
                    if unmapped:
                        self.warnings.append(f"{entry['path']}: {len(unmapped)} result(s) outside the project ignored")
            except (OSError, ValueError, KeyError) as e:
                self.errors.append(f"ingest[{i}]: cannot parse {entry['path']} as {kind}: {e}")

        ci_job = os.environ.get("CI_JOB_ID") or os.environ.get("GITHUB_RUN_ID")
        for (tid, env), (outcome, ts) in sorted(results.items()):
            e = {"id": f"result:{tid.removeprefix('test:')}@{env}", "kind": "test_result", "test": tid,
                 "environment": f"env:{env}", "outcome": outcome, "run_at": ts or self.now}
            if ci_job:
                e["ci_job"] = ci_job
            self.add(e)

        for (env, level), files in sorted(coverage.items()):
            for rel, fc in sorted(files.items()):
                for start, end, cid in self.unit_ranges.get(rel, []):
                    m = unit_metrics(fc, start, end)
                    if m:
                        self.add({"id": f"cov:{cid.removeprefix('code:')}@{env}/{level}", "kind": "coverage_record",
                                  "code_unit": cid, "environment": f"env:{env}", "test_level": level, "metrics": m})
        self.sarif = sarif

    def findings(self, cfg):
        devs = []
        spec = cfg.get("deviations")
        if spec:
            p = self.root / spec["path"]
            try:
                data = load_yaml(p, "deviations file") or []
            except FormatError as e:
                self.errors.append(str(e))
                data = []
            errs = schema_errors(load_schema("deviations.schema.json"), data, f"deviations {spec['path']}")
            self.errors += errs
            if not errs:
                self.artifact(p, spec["section"], "application/yaml", "deviation register")
                devs = data
        for d in devs:
            person = f"person:{d['approved_by']}"
            if person not in self.entities:
                self.errors.append(f"deviation {d['key']}: approved_by {d['approved_by']!r} is not in people")
            self.add({"id": f"dev:{d['key']}", "kind": "deviation", "key": d["key"], "justification": d["justification"],
                      "approved_by": person, "approved_at": d["approved_at"], "expires_at": d["expires_at"],
                      **({"scope": d["scope"]} if d.get("scope") else {})})

        used_devs, seen = set(), {}
        for r in sorted(self.sarif, key=lambda r: (r.tool, r.rule_id, r.path, r.line or 0)):
            tool_id = self.tool_by_name.get(r.tool.lower())
            if tool_id is None:
                tool_id = f"tool:{_slug(r.tool)}"
                self.tool_by_name[r.tool.lower()] = tool_id
                self.add({"id": tool_id, "kind": "tool", "name": r.tool, "version": r.tool_version or "unknown",
                          "class": None, "evidence": []})
                self.warnings.append(f"tool {r.tool!r} reported findings but is not in config tools; recorded as unclassified")
            # Prefer the tool's fingerprint: line numbers shift with unrelated edits and would churn gap ids.
            anchor = f"#{r.fingerprint[:16]}" if r.fingerprint else f":{r.line or 0}"
            base = f"finding:{tool_id.removeprefix('tool:')}/{r.rule_id}/{r.path}{anchor}"
            seen[base] = seen.get(base, 0) + 1
            fid = base if seen[base] == 1 else f"{base}#{seen[base]}"
            matching = [d for d in devs if self._dev_matches(d["match"], r, tool_id)]
            e = {"id": fid, "kind": "finding", "tool": tool_id, "rule_id": r.rule_id, "message": r.message,
                 "location": {"path": r.path, **({"line": r.line} if r.line else {})},
                 "severity": r.level if r.level in ("error", "warning", "note", "none") else "warning",
                 "state": "deviated" if matching else "open"}
            if r.fingerprint:
                e["fingerprint"] = r.fingerprint
            if r.suppressed_in_source:
                e["extra"] = {"suppressed_in_source": True}
            self.add(e)
            for d in matching:
                self.link("justifies", f"dev:{d['key']}", fid)
                used_devs.add(d["key"])
        for d in devs:
            if d["key"] not in used_devs:
                self.warnings.append(f"deviation {d['key']} matches no current finding (stale?)")

    def _dev_matches(self, m, r, tool_id):
        if m["tool"].lower() not in (r.tool.lower(), tool_id.removeprefix("tool:")):
            return False
        if m["rule"] != r.rule_id:
            return False
        if "path" in m and m["path"] != r.path:
            return False
        if "line" in m and m["line"] != r.line:
            return False
        if "fingerprint" in m and m["fingerprint"] != r.fingerprint:
            return False
        return True

    def bundle(self, cfg, std, std_path, previous, baseline_id, commit):
        commit = commit or _git(self.root, "rev-parse", "HEAD")
        if not commit:
            self.warnings.append("not a git checkout; baseline commit recorded as all zeros")
            commit = "0" * 40
        tag = _git(self.root, "describe", "--tags", "--exact-match")
        baseline = {"id": baseline_id or tag or f"commit-{commit[:12]}", "commit": commit,
                    "previous_bundle_hash": canonical_hash(previous) if previous else None}
        if tag:
            baseline["tag"] = tag
        ents = sorted(self.entities.values(), key=lambda e: (KIND_ORDER[e["kind"]], e["id"]))
        links = []
        for typ, frm, to, decl in sorted(self.links, key=lambda l: (l[0], l[1], l[2], l[3] or ())):
            l = {"type": typ, "from": frm, "to": to}
            if decl:
                l["declared_at"] = dict(decl)
            links.append(l)
        return {
            "bundle_format": "0.1.0",
            "generator": {"name": GENERATOR, "version": __version__},
            "created_at": self.now,
            "project": {"id": cfg["project"]["id"], "name": cfg["project"]["name"],
                        "integrity_claim": cfg["project"]["integrity_claim"],
                        "standard": {"id": std.id, "edition": std.edition, "data_hash": file_hash(std_path)}},
            "baseline": baseline,
            "entities": ents,
            "links": links,
            "artifacts": [self.artifacts[k] for k in sorted(self.artifacts)],
        }


def build(config_path, previous=None, baseline_id=None, commit=None, now=None):
    b = _Builder(config_path, now)
    try:
        cfg, errs = load_config(config_path)
    except FormatError as e:
        return BuildResult(None, [str(e)])
    if errs:
        return BuildResult(None, errs, root=b.root)

    std_path = b.root / cfg["standard"]
    try:
        std_data, errs = check_standard(std_path)
    except FormatError as e:
        return BuildResult(None, [str(e)], root=b.root)
    if errs:
        return BuildResult(None, errs, root=b.root)
    std = StandardIndex(std_data)

    b.items(cfg)
    b.people_tools(cfg)
    b.code(cfg)
    b.ingest(cfg)
    b.findings(cfg)
    bundle = b.bundle(cfg, std, std_path, previous, baseline_id, commit)

    errors = list(b.errors)
    if not errors:
        errors += check_bundle_schema(bundle)
    if not errors:
        errors += check_references(bundle, std, std_path, b.root)
    return BuildResult(bundle if not errors else None, errors, b.warnings, b.root, std, std_path)
