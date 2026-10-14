"""Parsers for CI outputs: JUnit XML, lcov, Cobertura XML, SARIF."""
import datetime as dt
import json
import pathlib
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass

OUTCOME_RANK = {"error": 3, "fail": 2, "pass": 1, "skip": 0}


# ------------------------------------------------------------------ paths

def normalize_path(raw, repo_root, known_paths=()):
    """Map a path reported by a tool to a repo-relative POSIX path, or None if it lies outside the repo."""
    raw = raw.removeprefix("file://")
    p = pathlib.PurePosixPath(raw)
    root = pathlib.PurePosixPath(pathlib.Path(repo_root).resolve().as_posix())
    if p.is_absolute():
        try:
            return p.relative_to(root).as_posix()
        except ValueError:
            for k in known_paths:   # tool ran in another checkout location
                if raw.endswith("/" + k):
                    return k
            return None
    rel = pathlib.PurePosixPath(*[part for part in p.parts if part != "."]).as_posix()
    return None if rel.startswith("..") else rel


# ------------------------------------------------------------------ JUnit

@dataclass
class JunitCase:
    classname: str
    name: str
    outcome: str
    timestamp: str | None


def _iso_utc(ts):
    if not ts:
        return None
    try:
        t = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.astimezone()   # naive timestamps from pytest are local time
    return t.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_junit(path):
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else root.iter("testsuite")
    cases = []
    for suite in suites:
        ts = _iso_utc(suite.get("timestamp"))
        for tc in suite.findall("testcase"):
            if tc.find("error") is not None:
                outcome = "error"
            elif tc.find("failure") is not None:
                outcome = "fail"
            elif tc.find("skipped") is not None:
                outcome = "skip"
            else:
                outcome = "pass"
            cases.append(JunitCase(tc.get("classname", ""), tc.get("name", ""), outcome, ts))
    return cases


def junit_match_keys(test_path, symbol):
    """Keys a JUnit testcase may use for a test: pytest dotted module path, or the bare symbol."""
    keys = {symbol}
    if test_path.endswith(".py"):
        module = test_path[:-3].replace("/", ".")
        keys.add(f"{module}.{symbol}")
    return keys


def match_junit(cases, tests):
    """tests: {test_entity_id: (path, symbol)}. Returns ({test_id: outcome}, unmatched_case_labels)."""
    exact, by_last = defaultdict(set), defaultdict(set)
    for tid, (path, symbol) in tests.items():
        for k in junit_match_keys(path, symbol):
            exact[k].add(tid)
        by_last[symbol.rsplit(".", 1)[-1]].add(tid)

    def only(candidates):
        # Ambiguity is never resolved by guessing: crediting a result to the wrong test is worse than none.
        return next(iter(candidates)) if len(candidates) == 1 else None

    outcomes, unmatched = {}, []
    for c in cases:
        name = re.sub(r"\[.*\]$", "", c.name)   # pytest parametrisation
        tid = only(exact.get(f"{c.classname}.{name}", set())) if c.classname else None
        tid = tid or only(exact.get(name, set()))
        if tid is None:
            tid = only(by_last.get(re.split(r"\.|::", name)[-1], set()))
        if tid is None:
            unmatched.append(f"{c.classname}.{c.name}" if c.classname else c.name)
            continue
        prev = outcomes.get(tid)
        if prev is None or OUTCOME_RANK[c.outcome] > OUTCOME_RANK[prev[0]]:   # error > fail > pass > skip
            outcomes[tid] = (c.outcome, c.timestamp)
    return outcomes, unmatched


# ------------------------------------------------------------------ coverage

@dataclass
class FileCoverage:
    lines: dict      # line -> hits
    branches: dict   # line -> (covered, total)


def parse_lcov(path, repo_root, known_paths=()):
    files, current, unmapped = {}, None, []
    for raw in pathlib.Path(path).read_text().splitlines():
        if raw.startswith("SF:"):
            rel = normalize_path(raw[3:], repo_root, known_paths)
            if rel is None:
                unmapped.append(raw[3:])
            current = files.setdefault(rel, FileCoverage({}, {})) if rel else None
        elif current is None:
            continue
        elif raw.startswith("DA:"):
            line, hits = raw[3:].split(",")[:2]
            current.lines[int(line)] = current.lines.get(int(line), 0) + int(hits)
        elif raw.startswith("BRDA:"):
            parts = raw[5:].split(",")
            line, taken = parts[0], parts[-1]
            cov, tot = current.branches.get(int(line), (0, 0))
            current.branches[int(line)] = (cov + (taken not in ("-", "0")), tot + 1)
    return files, unmapped


def parse_cobertura(path, repo_root, known_paths=()):
    root = ET.parse(path).getroot()
    sources = [s.text.strip() for s in root.iter("source") if s.text and s.text.strip()] or [""]
    files, unmapped = {}, []
    for cls in root.iter("class"):
        fname = cls.get("filename", "")
        rel = None
        for src in sources:
            candidate = fname if not src or fname.startswith("/") else f"{src.rstrip('/')}/{fname}"
            rel = normalize_path(candidate, repo_root, known_paths)
            if rel:
                break
        if rel is None:
            unmapped.append(fname)
            continue
        fc = files.setdefault(rel, FileCoverage({}, {}))
        for ln in cls.iter("line"):
            n = int(ln.get("number"))
            fc.lines[n] = fc.lines.get(n, 0) + int(ln.get("hits", "0"))
            m = re.search(r"\((\d+)/(\d+)\)", ln.get("condition-coverage", ""))
            if ln.get("branch") == "true" and m:
                fc.branches[n] = (int(m.group(1)), int(m.group(2)))
    return files, unmapped


def unit_metrics(fc, start, end):
    """Statement and branch counts for one code unit's line range, or None if nothing instrumented."""
    lines = [h for ln, h in fc.lines.items() if start <= ln <= end]
    if not lines:
        return None
    metrics = {"statement": {"covered": sum(1 for h in lines if h > 0), "total": len(lines)}}
    br = [v for ln, v in fc.branches.items() if start <= ln <= end]
    if br:
        metrics["branch"] = {"covered": sum(c for c, _ in br), "total": sum(t for _, t in br)}
    return metrics


# ------------------------------------------------------------------ SARIF

@dataclass
class SarifResult:
    tool: str
    tool_version: str | None
    rule_id: str
    message: str
    path: str
    line: int | None
    level: str
    fingerprint: str | None
    suppressed_in_source: bool


def parse_sarif(path, repo_root, known_paths=()):
    doc = json.loads(pathlib.Path(path).read_text())
    out, unmapped = [], []
    for run in doc.get("runs", []):
        driver = run.get("tool", {}).get("driver", {})
        tool = driver.get("name", "unknown")
        version = driver.get("semanticVersion") or driver.get("version")
        rule_levels = {r.get("id"): r.get("defaultConfiguration", {}).get("level")
                       for r in driver.get("rules", [])}
        for r in run.get("results", []):
            locs = r.get("locations") or [{}]
            phys = locs[0].get("physicalLocation", {})
            uri = phys.get("artifactLocation", {}).get("uri", "")
            rel = normalize_path(uri, repo_root, known_paths) if uri else None
            if rel is None:
                unmapped.append(uri or "<no location>")
                continue
            rule_id = r.get("ruleId") or "unknown"
            fps = r.get("partialFingerprints") or r.get("fingerprints") or {}
            out.append(SarifResult(
                tool=tool,
                tool_version=version,
                rule_id=rule_id,
                message=(r.get("message") or {}).get("text", ""),
                path=rel,
                line=phys.get("region", {}).get("startLine"),
                level=r.get("level") or rule_levels.get(rule_id) or "warning",
                fingerprint=next(iter(sorted(fps.values())), None) if fps else None,
                suppressed_in_source=bool(r.get("suppressions")),
            ))
    return out, unmapped
