"""Self-contained static HTML report: gate result, traceability matrix, code units, findings, manifest."""
from collections import defaultdict
from html import escape

from .gates import RULES

CSS = """
:root{--bg:#fbfaf7;--fg:#1d1d1b;--muted:#6b6862;--line:#e3dfd6;--card:#fff;--ok:#1f7a4a;--bad:#b42318;--warn:#a15c07;--chip:#f1eee6}
@media (prefers-color-scheme:dark){:root{--bg:#161614;--fg:#ecebe6;--muted:#a3a097;--line:#34332f;--card:#1e1e1b;--ok:#4cc38a;--bad:#ff7b6b;--warn:#f0b35a;--chip:#2a2926}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1200px;margin:0 auto;padding:24px 16px 64px}h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:32px 0 8px}
.meta{color:var(--muted);font-size:13px}.meta code{font-size:12px}
.banner{margin:20px 0;padding:14px 16px;border-radius:8px;border:1px solid var(--line);background:var(--card);display:flex;gap:16px;align-items:center;flex-wrap:wrap}
.badge{font-weight:700;padding:3px 10px;border-radius:999px;color:#fff}.pass{background:var(--ok)}.fail{background:var(--bad)}
.wrap{overflow-x:auto;border:1px solid var(--line);border-radius:8px;background:var(--card)}
table{border-collapse:collapse;width:100%;min-width:760px;font-size:13px}th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-weight:600;color:var(--muted);white-space:nowrap}tr:last-child td{border-bottom:0}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}
.chip{display:inline-block;background:var(--chip);border-radius:4px;padding:0 6px;margin:1px 2px 1px 0;white-space:nowrap}
.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}.muted{color:var(--muted)}.new{color:var(--bad);font-weight:600}
ul.plain{margin:0;padding-left:18px}.nw{white-space:nowrap}
"""


def _e(s):
    return escape(str(s), quote=True)


def _short(eid):
    return eid.split(":", 1)[1]


def _pct(m):
    if not m or not m["total"]:
        return "—"
    v = 100 * m["covered"] / m["total"]
    cls = "ok" if m["covered"] == m["total"] else ("warn" if v >= 80 else "bad")
    return f'<span class="nw"><span class="{cls}">{v:.0f}%</span> <span class="muted">{m["covered"]}/{m["total"]}</span></span>'


def render(bundle, gaps, new_ids=None, fixed=None, warnings=None):
    ents = {e["id"]: e for e in bundle["entities"]}
    by_kind = defaultdict(list)
    for e in bundle["entities"]:
        by_kind[e["kind"]].append(e)
    out_l, in_l = defaultdict(list), defaultdict(list)
    for l in bundle["links"]:
        out_l[l["from"]].append(l)
        in_l[l["to"]].append(l)
    results = defaultdict(list)
    for r in by_kind["test_result"]:
        results[r["test"]].append(r)
    cov = defaultdict(list)
    for c in by_kind["coverage_record"]:
        cov[c["code_unit"]].append(c)

    ratcheted = new_ids is not None
    failing = [g for g in gaps if g.id in new_ids] if ratcheted else gaps
    p, b = bundle["project"], bundle["baseline"]
    h = []
    h.append(f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
             f"<title>Traceability report</title><style>{CSS}</style></head><body><main>")
    h.append(f"<h1>{_e(p['name'])}</h1>")
    h.append(f"<div class='meta'>{_e(p['standard']['id'])} {_e(p['standard']['edition'])} · claim <b>{_e(p['integrity_claim'])}</b>"
             f" · baseline <b>{_e(b['id'])}</b> · commit <code>{_e(b['commit'][:12])}</code>"
             f" · generated {_e(bundle['created_at'])} by {_e(bundle['generator']['name'])} {_e(bundle['generator']['version'])}</div>")

    status = "fail" if failing else "pass"
    summary = f"{len(gaps)} gap(s)"
    if ratcheted:
        summary += f" — {len(failing)} new, {len(gaps) - len(failing)} carried from baseline, {len(fixed or [])} fixed"
    h.append(f"<div class='banner'><span class='badge {status}'>{status.upper()}</span><span>{_e(summary)}</span></div>")

    # Gaps
    h.append("<h2>Gaps</h2>")
    if gaps:
        h.append("<div class='wrap'><table><tr><th>Rule</th><th>Gap</th>" + ("<th></th>" if ratcheted else "") + "</tr>")
        for g in gaps:
            tag = ""
            if ratcheted:
                tag = "<td class='new'>new</td>" if g.id in new_ids else "<td class='muted'>baseline</td>"
            h.append(f"<tr><td title='{_e(RULES.get(g.rule, ''))}'>{g.rule}</td><td>{_e(g.message)}</td>{tag}</tr>")
        h.append("</table></div>")
    else:
        h.append("<p class='ok'>No gaps.</p>")
    if fixed:
        h.append("<p class='muted'>Fixed since baseline: " + "; ".join(_e(g.message) for g in fixed) + "</p>")

    # Requirements matrix
    h.append("<h2>Requirements</h2><div class='wrap'><table><tr><th>Key</th><th>Title</th><th>Level · type</th><th>Integrity</th>"
             "<th>Derives from</th><th>Design · code</th><th>Tests by level</th><th>Status</th></tr>")
    level_rank = {"system": 0, "software": 1, "derived": 2}
    for r in sorted(by_kind["requirement"], key=lambda r: (level_rank[r["level"]], r["key"])):
        parents = [ents[l["to"]]["key"] for l in out_l[r["id"]] if l["type"] == "derives_from"]
        impl = [l["from"] for l in in_l[r["id"]] if l["type"] == "satisfies"]
        impl_html = " ".join(f"<span class='chip'>{_e(ents[i].get('key') or _short(i))}</span>" for i in sorted(impl)) or "<span class='muted'>—</span>"
        tests = [ents[l["from"]] for l in in_l[r["id"]] if l["type"] == "verifies"]
        cells = []
        levels = list(dict.fromkeys(r.get("test_levels", []) + [t["level"] for t in tests]))
        for lvl in levels:
            at = [t for t in tests if t["level"] == lvl]
            if not at:
                cells.append(f"<div><b>{_e(lvl)}</b> <span class='bad'>missing</span></div>")
                continue
            items = []
            for t in at:
                outs = {x["outcome"] for x in results[t["id"]]}
                if outs & {"fail", "error"}:
                    mark = "<span class='bad'>✗ failed</span>"
                elif "pass" in outs:
                    envs = sorted(_short(x["environment"]) for x in results[t["id"]] if x["outcome"] == "pass")
                    mark = f"<span class='ok'>✓</span> <span class='muted'>{_e(', '.join(envs))}</span>"
                elif outs:
                    mark = "<span class='warn'>○ skipped</span>"
                else:
                    mark = "<span class='warn'>○ not run</span>"
                items.append(f"<li><code>{_e(t['name'].split('::')[-1])}</code> {mark}</li>")
            cells.append(f"<div><b>{_e(lvl)}</b><ul class='plain'>{''.join(items)}</ul></div>")
        tests_html = "".join(cells) or "<span class='muted'>—</span>"
        h.append(f"<tr><td><b>{_e(r['key'])}</b></td><td>{_e(r['title'])}</td><td>{_e(r['level'])} · {_e(r['type'])}</td>"
                 f"<td>{_e(r.get('integrity_level') or '—')}</td><td>{_e(', '.join(parents)) or '—'}</td>"
                 f"<td>{impl_html}</td><td>{tests_html}</td><td>{_e(r['status'])}</td></tr>")
    h.append("</table></div>")

    # Code units
    h.append("<h2>Code units</h2><div class='wrap'><table><tr><th>Unit</th><th>Traces to</th><th>Statement</th><th>Branch</th><th>Note</th></tr>")
    def unit_targets(uid):
        return sorted({ents[l["to"]].get("key", _short(l["to"])) for l in out_l[uid] if l["type"] in ("satisfies", "implements")})

    file_units = {u["path"]: u for u in by_kind["code_unit"] if u["symbol"] is None}
    for u in sorted(by_kind["code_unit"], key=lambda u: u["id"]):
        targets = unit_targets(u["id"])
        trace = " ".join(f"<span class='chip'>{_e(t)}</span>" for t in targets)
        note = ""
        parent = file_units.get(u["path"]) if u["symbol"] is not None else None
        if u["infrastructure"]:
            note = f"<span class='muted'>infrastructure: {_e(u['infrastructure']['reason'])}</span>"
        elif not targets and parent is not None and (parent["infrastructure"] or unit_targets(parent["id"])):
            trace = "<span class='muted'>via file</span>"
            note = f"<span class='muted'>covered by the file-level annotation on {_e(u['path'])}</span>"
        elif not targets:
            trace = "<span class='bad'>untraced</span>"
        stmt = br = "—"
        if cov[u["id"]]:
            c = cov[u["id"]][0]["metrics"]
            stmt, br = _pct(c.get("statement")), _pct(c.get("branch"))
        h.append(f"<tr><td><code>{_e(_short(u['id']))}</code></td><td>{trace or '—'}</td><td>{stmt}</td><td>{br}</td><td>{note}</td></tr>")
    h.append("</table></div>")

    # Findings
    h.append("<h2>Static analysis findings</h2>")
    if by_kind["finding"]:
        h.append("<div class='wrap'><table><tr><th>Rule</th><th>Location</th><th>Tool</th><th>State</th><th>Deviation</th></tr>")
        for f in sorted(by_kind["finding"], key=lambda f: f["id"]):
            devs = [ents[l["from"]] for l in in_l[f["id"]] if l["type"] == "justifies"]
            dev_html = "<br>".join(f"<b>{_e(d['key'])}</b> {_e(d['justification'])} <span class='muted'>(expires {_e(d['expires_at'] or 'never')})</span>" for d in devs) or "—"
            state_cls = "bad" if f["state"] == "open" else "muted"
            loc = f"{f['location']['path']}:{f['location'].get('line', '?')}"
            h.append(f"<tr><td><code>{_e(f['rule_id'])}</code><div class='muted'>{_e(f.get('message', ''))}</div></td><td><code>{_e(loc)}</code></td>"
                     f"<td>{_e(ents[f['tool']]['name'])}</td><td class='{state_cls}'>{_e(f['state'])}</td><td>{dev_html}</td></tr>")
        h.append("</table></div>")
    else:
        h.append("<p class='muted'>None ingested.</p>")

    # Tools and pre-existing software
    h.append("<h2>Tools</h2><div class='wrap'><table><tr><th>Tool</th><th>Version</th><th>Class</th><th>Evidence</th></tr>")
    for t in sorted(by_kind["tool"], key=lambda t: t["name"].lower()):
        cls = _e(t["class"]) if t["class"] else "<span class='warn'>unclassified</span>"
        h.append(f"<tr><td>{_e(t['name'])}</td><td><code>{_e(t['version'])}</code></td><td>{cls}</td><td>{_e(', '.join(t.get('evidence', []))) or '—'}</td></tr>")
    h.append("</table></div>")
    if by_kind["preexisting_element"]:
        h.append("<h2>Pre-existing software</h2><div class='wrap'><table><tr><th>Element</th><th>Version</th><th>Route</th><th>Justification</th></tr>")
        for x in by_kind["preexisting_element"]:
            route = _e(x["route"]) if x["route"] else "<span class='warn'>not routed</span>"
            h.append(f"<tr><td>{_e(x['name'])}</td><td><code>{_e(x['version'])}</code></td><td>{route}</td><td>{_e(', '.join(x.get('justification', []))) or '—'}</td></tr>")
        h.append("</table></div>")

    # Manifest
    h.append("<h2>Artifact manifest</h2><div class='wrap'><table><tr><th>Path</th><th>Section</th><th>sha256</th></tr>")
    for a in bundle["artifacts"]:
        h.append(f"<tr><td><code>{_e(a['path'])}</code></td><td>{_e(a['section'])}</td><td><code>{_e(a['hash'][7:23])}…</code></td></tr>")
    h.append("</table></div>")
    if b.get("previous_bundle_hash"):
        h.append(f"<p class='meta'>Chained to previous bundle <code>{_e(b['previous_bundle_hash'])}</code></p>")

    if warnings:
        h.append("<h2>Build warnings</h2><ul>" + "".join(f"<li class='warn'>{_e(w)}</li>" for w in warnings) + "</ul>")
    h.append("</main></body></html>")
    return "\n".join(h)
