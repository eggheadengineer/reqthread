"""Schema loading, hashing, and format/reference validation for bundles, standard data and item files."""
import datetime as dt
import hashlib
import json
import pathlib
import re
from importlib import resources

import yaml
from jsonschema import Draft202012Validator

PREFIX = {
    "requirement": "req", "architecture_element": "arch", "design_element": "design",
    "code_unit": "code", "test_case": "test", "environment": "env", "test_result": "result",
    "coverage_record": "cov", "finding": "finding", "deviation": "dev", "review": "review",
    "tool": "tool", "preexisting_element": "pre", "technique_status": "tech",
    "change": "change", "person": "person", "hazard": "haz", "cause": "cause",
}

TRACEABLE = ("requirement", "architecture_element", "design_element", "code_unit", "test_case")
LINK_PAIRS = {
    "derives_from": {("requirement", "requirement"), ("design_element", "architecture_element")},
    "allocated_to": {("requirement", "architecture_element")},
    "satisfies": {("design_element", "requirement"), ("code_unit", "requirement")},
    "implements": {("code_unit", "design_element"), ("code_unit", "architecture_element")},
    "verifies": {("test_case", k) for k in ("requirement", "design_element", "architecture_element")},
    "covers": {("test_case", "code_unit")},
    "justifies": {("deviation", "finding")},
    "reviews": {("review", k) for k in TRACEABLE + ("change",)},
    "affects": {("change", k) for k in TRACEABLE},
    "supersedes": {("requirement", "requirement")},
    "mitigates": {("requirement", "hazard"), ("requirement", "cause")},
    "leads_to": {("cause", "hazard")},
    "located_in": {("cause", "architecture_element")},
}

REF_FIELDS = {
    "test_result": {"test": "test_case", "environment": "environment"},
    "coverage_record": {"code_unit": "code_unit", "environment": "environment"},
    "finding": {"tool": "tool"},
    "deviation": {"approved_by": "person"},
    "review": {"author": "person", "approvers": "person"},
    "change": {"author": "person"},
}
# nested person reference: cause.accepted.approved_by


FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.S)
_schemas = {}


class FormatError(Exception):
    """Raised for inputs that cannot be used at all (unreadable, not YAML, wrong shape)."""


def load_schema(name):
    if name not in _schemas:
        text = resources.files("reqthread").joinpath("schema", name).read_text()
        _schemas[name] = json.loads(text)
    return _schemas[name]


def file_hash(path):
    return "sha256:" + hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def _reject_floats(obj, where="$"):
    if isinstance(obj, float):
        raise ValueError(f"floating-point value at {where}; bundles must contain only integers")
    if isinstance(obj, dict):
        for k, v in obj.items():
            _reject_floats(v, f"{where}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _reject_floats(v, f"{where}[{i}]")


def canonical_hash(obj):
    """sha256 over the canonical serialisation of a bundle.

    For float-free JSON with ASCII object keys — which every bundle is — sorted-key
    compact serialisation is identical to RFC 8785 (JCS). Floats are rejected so
    that equivalence holds.
    """
    _reject_floats(obj)
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def schema_errors(schema, instance, label):
    out = []
    for e in sorted(Draft202012Validator(schema).iter_errors(instance), key=lambda e: list(e.path)):
        where = "/".join(map(str, e.path)) or "<root>"
        out.append(f"{label}: {where}: {e.message}")
    return out


def dates_to_str(obj):
    """YAML turns timestamps into datetime/date objects; formats carry them as ISO 8601 strings."""
    if isinstance(obj, dt.datetime):
        s = obj.isoformat()
        return s[:-6] + "Z" if s.endswith("+00:00") else s
    if isinstance(obj, dt.date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: dates_to_str(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [dates_to_str(v) for v in obj]
    return obj


def load_yaml(path, what):
    try:
        return dates_to_str(yaml.safe_load(pathlib.Path(path).read_text()))
    except FileNotFoundError:
        raise FormatError(f"{what} not found: {path}") from None
    except yaml.YAMLError as e:
        raise FormatError(f"{what} is not valid YAML: {path}: {e}") from None


# ---------------------------------------------------------------- standard data

def check_standard(path):
    data = load_yaml(path, "standard data")
    errors = schema_errors(load_schema("standard-data.schema.json"), data, f"standard {path}")
    if errors:
        return data, errors

    levels = {l["id"] for l in data["integrity_levels"]}
    codes = {r["code"] for r in data["recommendation_scale"]}
    sections = {s["id"] for s in data["package_sections"]}
    for t in data["techniques"]:
        if t["section"] not in sections:
            errors.append(f"standard: technique {t['id']}: unknown section {t['section']!r}")
        for lvl, code in t["levels"].items():
            if lvl not in levels:
                errors.append(f"standard: technique {t['id']}: unknown integrity level {lvl!r}")
            if code not in codes:
                errors.append(f"standard: technique {t['id']}: unknown recommendation code {code!r}")
    for c in data["coverage_expectations"]:
        if c["integrity_level"] not in levels:
            errors.append(f"standard: coverage expectation: unknown integrity level {c['integrity_level']!r}")
        if c["strength"] not in codes:
            errors.append(f"standard: coverage expectation: unknown recommendation code {c['strength']!r}")
    return data, errors


class StandardIndex:
    """Id sets from standard data, for conformance checks."""

    def __init__(self, data):
        self.data = data
        self.id = data["standard"]["id"]
        self.edition = data["standard"]["edition"]
        self.levels = {l["id"] for l in data["integrity_levels"]}
        self.test_levels = {t["id"] for t in data["test_levels"]}
        self.tool_classes = {t["id"]: t for t in data["tool_classes"]}
        self.routes = {r["id"] for r in data["preexisting_routes"]}
        self.sections = {s["id"] for s in data["package_sections"]}
        self.techniques = {t["id"] for t in data["techniques"]}


# ---------------------------------------------------------------- item files

def parse_item_file(path):
    """Return (front_matter, title, text, rationale) for a *.req.md / *.arch.md / *.design.md file."""
    raw = pathlib.Path(path).read_text()
    m = FRONT_MATTER.match(raw)
    if not m:
        return None, None, None, None
    try:
        fm = dates_to_str(yaml.safe_load(m.group(1)))
    except yaml.YAMLError as e:
        raise FormatError(f"{path}: front matter is not valid YAML: {e}") from None
    body = m.group(2)
    h1 = re.search(r"^# (.+)$", body, re.M)
    title = h1.group(1).strip() if h1 else None
    after_title = body[h1.end():] if h1 else body
    parts = re.split(r"^## Rationale\s*$", after_title, maxsplit=1, flags=re.M)
    text = parts[0].strip()
    rationale = parts[1].strip() if len(parts) > 1 else None
    return fm, title, text, rationale


ITEM_KINDS = {
    ".req.md": ("requirement.schema.json", "requirement"),
    ".arch.md": ("architecture.schema.json", "architecture element"),
    ".design.md": ("design.schema.json", "design element"),
    ".hazard.md": ("hazard.schema.json", "hazard"),
    ".cause.md": ("cause.schema.json", "cause"),
}


def check_item_files(directory, suffix=".req.md"):
    """Validate every item file of one kind in a directory. Returns (errors, {id: (path, fm, title, text, rationale)})."""
    schema_name, what = ITEM_KINDS[suffix]
    schema = load_schema(schema_name)
    errors, items = [], {}
    for f in sorted(pathlib.Path(directory).rglob(f"*{suffix}")):
        fm, title, text, rationale = parse_item_file(f)
        if fm is None:
            errors.append(f"{what} file {f}: no YAML front matter")
            continue
        file_errors = schema_errors(schema, fm, f"{what} file {f}")
        errors += file_errors
        if not title:
            errors.append(f"{what} file {f}: body has no '# ' title")
        if suffix in (".req.md", ".hazard.md") and not text:
            errors.append(f"{what} file {f}: no {what} text after the title")
        rid = fm.get("id") if isinstance(fm, dict) else None
        if rid in items:
            errors.append(f"{what} file {f}: duplicate id {rid} (also {items[rid][0]})")
        if rid and f.name != f"{rid}{suffix}":
            errors.append(f"{what} file {f}: file name should be {rid}{suffix}")
        if rid and not file_errors:
            items[rid] = (f, fm, title, text, rationale)
    return errors, items


def check_requirement_files(directory):
    """Validate a directory of requirement files, including derives_from targets among them."""
    errors, items = check_item_files(directory, ".req.md")
    for rid, (f, fm, *_rest) in items.items():
        for parent in fm.get("derives_from", []):
            if parent not in items:
                errors.append(f"requirement file {f}: derives_from unknown requirement {parent}")
    return errors, len(list(pathlib.Path(directory).rglob("*.req.md")))


# ---------------------------------------------------------------- bundles

def check_bundle_schema(bundle):
    schema = load_schema("bundle.schema.json")
    errors, bad_entities = [], set()
    for e in Draft202012Validator(schema).iter_errors(bundle):
        path = list(e.path)
        if len(path) >= 2 and path[0] == "entities":
            bad_entities.add(path[1])  # re-validated per kind below for readable errors
            continue
        errors.append(f"bundle: {'/'.join(map(str, path)) or '<root>'}: {e.message}")

    for i in sorted(bad_entities):
        ent = bundle["entities"][i]
        kind = ent.get("kind") if isinstance(ent, dict) else None
        if kind not in PREFIX:
            errors.append(f"bundle: entities/{i}: unknown kind {kind!r}")
            continue
        sub = {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": f"#/$defs/{kind}"}
        errors += schema_errors(sub, ent, f"bundle: entities/{i} ({ent.get('id')})")
    return errors


def check_references(bundle, std=None, std_path=None, root=None):
    """Referential integrity, standard-data conformance, and (with root) artifact hashes."""
    errors = []
    by_id = {}
    for e in bundle["entities"]:
        if e["id"] in by_id:
            errors.append(f"refs: duplicate entity id {e['id']}")
        by_id[e["id"]] = e

    def kind_of(ref):
        return by_id[ref]["kind"] if ref in by_id else None

    for e in bundle["entities"]:
        for field, want in REF_FIELDS.get(e["kind"], {}).items():
            vals = e.get(field)
            for ref in (vals if isinstance(vals, list) else [vals]):
                if ref is not None and kind_of(ref) != want:
                    errors.append(f"refs: {e['id']}.{field} -> {ref}: expected an existing {want}")

    for e in bundle["entities"]:
        if e["kind"] == "cause" and e.get("accepted"):
            ref = e["accepted"]["approved_by"]
            if kind_of(ref) != "person":
                errors.append(f"refs: {e['id']}.accepted.approved_by -> {ref}: expected an existing person")

    for i, l in enumerate(bundle["links"]):
        fk, tk = kind_of(l["from"]), kind_of(l["to"])
        if fk is None or tk is None:
            missing = l["from"] if fk is None else l["to"]
            errors.append(f"refs: links/{i} ({l['type']}): unknown entity {missing}")
        elif (fk, tk) not in LINK_PAIRS[l["type"]]:
            errors.append(f"refs: links/{i}: {l['type']} not allowed from {fk} to {tk}")

    if std is not None:
        s = std if isinstance(std, StandardIndex) else StandardIndex(std)
        proj = bundle["project"]
        if proj["standard"]["id"] != s.id:
            errors.append(f"std: bundle targets {proj['standard']['id']}, standard data is {s.id}")
        if std_path is not None and proj["standard"]["data_hash"] != file_hash(std_path):
            errors.append("std: project.standard.data_hash does not match the loaded standard-data file")
        if proj["integrity_claim"] not in s.levels:
            errors.append(f"std: integrity_claim {proj['integrity_claim']!r} not in standard")

        for e in bundle["entities"]:
            k, eid = e["kind"], e["id"]
            if k in ("requirement", "architecture_element") and e.get("integrity_level") not in (None, *s.levels):
                errors.append(f"std: {eid}: unknown integrity level {e['integrity_level']!r}")
            if k == "requirement":
                for t in e.get("test_levels", []):
                    if t not in s.test_levels:
                        errors.append(f"std: {eid}: unknown test level {t!r}")
            if k == "test_case" and e["level"] not in s.test_levels:
                errors.append(f"std: {eid}: unknown test level {e['level']!r}")
            if k == "coverage_record" and e["test_level"] not in s.test_levels:
                errors.append(f"std: {eid}: unknown test level {e['test_level']!r}")
            if k == "tool" and e["class"] is not None and e["class"] not in s.tool_classes:
                errors.append(f"std: {eid}: unknown tool class {e['class']!r}")
            if k == "preexisting_element" and e["route"] is not None and e["route"] not in s.routes:
                errors.append(f"std: {eid}: unknown route {e['route']!r}")
            if k == "technique_status" and e["technique"] not in s.techniques:
                errors.append(f"std: {eid}: unknown technique {e['technique']!r}")
            if k == "review" and e.get("section") and e["section"] not in s.sections:
                errors.append(f"std: {eid}: unknown section {e['section']!r}")
        for a in bundle["artifacts"]:
            if a["section"] not in s.sections:
                errors.append(f"std: artifact {a['path']}: unknown section {a['section']!r}")

    if root is not None:
        root = pathlib.Path(root)
        for a in bundle["artifacts"]:
            p = root / a["path"]
            if not p.is_file():
                errors.append(f"artifacts: {a['path']}: missing under {root}")
            elif file_hash(p) != a["hash"]:
                errors.append(f"artifacts: {a['path']}: hash mismatch")
        for e in bundle["entities"]:
            if e["kind"] == "requirement" and "source" in e:
                p = root / e["source"]["path"]
                if p.is_file():
                    fm, title, _text, _rat = parse_item_file(p)
                    if fm and fm.get("id") != e["key"]:
                        errors.append(f"refs: {e['id']}: source file id is {fm.get('id')!r}")
                    if title and title != e["title"]:
                        errors.append(f"refs: {e['id']}: title differs from source file")
    return errors
