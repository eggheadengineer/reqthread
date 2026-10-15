"""Gate rules. Each gap carries a stable id so a build can be ratcheted against a baseline."""
import datetime as dt
from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class Gap:
    rule: int
    subject: str      # entity id the gap is about
    qualifier: str    # distinguishes several gaps of one rule on one subject
    message: str

    @property
    def id(self):
        return f"rule{self.rule}:{self.subject}:{self.qualifier}"

    def as_dict(self):
        return {"id": self.id, "rule": self.rule, "subject": self.subject, "message": self.message}


RULES = {
    1: "Every software safety requirement has a verifying test at each declared test level.",
    2: "Every software safety requirement derives from a system-level requirement.",
    3: "Every code unit traces to a requirement or design element, or is marked infrastructure.",
    4: "Every test verifying a safety requirement passed at baseline and failed nowhere.",
    7: "Every static-analysis finding is fixed or covered by an unexpired deviation.",
    11: "Every hazard is mitigated by at least one requirement, directly or through one of its causes.",
    12: "Every cause is mitigated by a requirement, or its residual risk is formally accepted.",
    13: "Every requirement that mitigates a hazard or cause is a safety requirement with an integrity level.",
}


def evaluate(bundle):
    by_id = {e["id"]: e for e in bundle["entities"]}
    out_links, in_links = defaultdict(list), defaultdict(list)
    for l in bundle["links"]:
        out_links[l["from"]].append(l)
        in_links[l["to"]].append(l)

    def ents(kind):
        return [e for e in bundle["entities"] if e["kind"] == kind]

    gaps = []
    ssrs = [r for r in ents("requirement") if r["level"] in ("software", "derived") and r["status"] != "retired"]
    ssr_ids = {r["id"] for r in ssrs}

    # Rule 1
    for r in ssrs:
        if "test" not in r.get("verification", []):
            continue
        tests = [by_id[l["from"]] for l in in_links[r["id"]] if l["type"] == "verifies"]
        for lvl in r.get("test_levels", []):
            if not any(t["level"] == lvl for t in tests):
                gaps.append(Gap(1, r["id"], lvl, f"{r['key']} has no verifying test at level '{lvl}'"))

    # Rule 2
    for r in ssrs:
        parents = [by_id[l["to"]] for l in out_links[r["id"]] if l["type"] == "derives_from"]
        ok = any(p["level"] == "system" for p in parents) if r["level"] == "software" else bool(parents)
        if not ok:
            want = "a system-level requirement" if r["level"] == "software" else "any requirement"
            gaps.append(Gap(2, r["id"], "source", f"{r['key']} does not derive from {want}"))

    # Rule 3 — a function is covered by its own trace, or by a file-level unit for the same path.
    def traced(unit):
        return unit["infrastructure"] is not None or any(
            l["type"] in ("satisfies", "implements") for l in out_links[unit["id"]])

    file_units = {u["path"]: u for u in ents("code_unit") if u["symbol"] is None}
    for u in ents("code_unit"):
        if traced(u):
            continue
        parent = file_units.get(u["path"]) if u["symbol"] is not None else None
        if parent is not None and traced(parent):
            continue
        gaps.append(Gap(3, u["id"], "trace", f"{u['id'].removeprefix('code:')} traces to no requirement or design element"))

    # Rule 4
    results_by_test = defaultdict(list)
    for res in ents("test_result"):
        results_by_test[res["test"]].append(res)
    verifying_tests = {l["from"] for l in bundle["links"] if l["type"] == "verifies" and l["to"] in ssr_ids}
    for tid in sorted(verifying_tests):
        verified = sorted({l["to"] for l in out_links[tid] if l["type"] == "verifies" and l["to"] in ssr_ids})
        keys = ", ".join(by_id[v]["key"] for v in verified)
        name = tid.removeprefix("test:")
        results = results_by_test.get(tid, [])
        for res in results:
            if res["outcome"] in ("fail", "error"):
                env = res["environment"]
                gaps.append(Gap(4, tid, f"{env}:{res['outcome']}",
                                f"{name} {res['outcome']}s on {env.removeprefix('env:')} (verifies {keys})"))
        if not any(r["outcome"] == "pass" for r in results):
            why = "only skipped" if results else "has no result"
            gaps.append(Gap(4, tid, "not-passed", f"{name} {why} at baseline (verifies {keys})"))

    # Rule 7
    as_of = dt.datetime.fromisoformat(bundle["created_at"].replace("Z", "+00:00")).date()
    for f in ents("finding"):
        where = f"{f['location']['path']}:{f['location'].get('line', '?')}"
        if f["state"] == "open":
            gaps.append(Gap(7, f["id"], "open", f"{f['rule_id']} at {where} is open"))
        elif f["state"] == "deviated":
            devs = [by_id[l["from"]] for l in in_links[f["id"]] if l["type"] == "justifies"]
            live = [d for d in devs if d["expires_at"] is None or dt.date.fromisoformat(d["expires_at"]) >= as_of]
            if not live:
                gaps.append(Gap(7, f["id"], "deviation", f"{f['rule_id']} at {where} has no unexpired deviation"))

    # Rules 11-13: hazard analysis
    live = lambda e: e["status"] != "retired"
    hazards = [h for h in ents("hazard") if live(h)]
    causes = [c for c in ents("cause") if live(c)]
    mitigators = lambda eid: [by_id[l["from"]] for l in in_links[eid] if l["type"] == "mitigates" and live(by_id[l["from"]])]
    cause_hazards = {c["id"]: [l["to"] for l in out_links[c["id"]] if l["type"] == "leads_to"] for c in causes}
    for h in hazards:
        direct = mitigators(h["id"])
        via = [c for c in causes if h["id"] in cause_hazards[c["id"]] and (mitigators(c["id"]) or c["accepted"])]
        if not direct and not via:
            gaps.append(Gap(11, h["id"], "unmitigated", f"{h['key']} ({h['title']}) has no mitigating requirement"))
    for c in causes:
        if not mitigators(c["id"]) and not c["accepted"]:
            gaps.append(Gap(12, c["id"], "unmitigated", f"{c['key']} ({c['title']}) has no mitigating requirement and no accepted-risk record"))
    for r in ents("requirement"):
        if live(r) and any(l["type"] == "mitigates" for l in out_links[r["id"]]) and not r.get("integrity_level"):
            gaps.append(Gap(13, r["id"], "integrity", f"{r['key']} mitigates a hazard but has no integrity level"))

    return sorted(gaps, key=lambda g: (g.rule, g.subject, g.qualifier))


def ratchet(current, baseline):
    """Split current gaps into (new, existing) relative to baseline gaps; also return fixed baseline gaps."""
    base_ids = {g.id for g in baseline}
    cur_ids = {g.id for g in current}
    new = [g for g in current if g.id not in base_ids]
    existing = [g for g in current if g.id in base_ids]
    fixed = [g for g in baseline if g.id not in cur_ids]
    return new, existing, fixed
