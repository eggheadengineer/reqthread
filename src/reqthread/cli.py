"""Command-line interface."""
import argparse
import json
import pathlib
import sys

from . import GENERATOR, __version__
from .build import build
from .formats import FormatError, check_bundle_schema, check_references, check_requirement_files, check_standard
from .gates import evaluate, ratchet
from .report import render

EXIT_OK, EXIT_ERRORS, EXIT_GAPS = 0, 1, 2


def _err(msg):
    print(msg, file=sys.stderr)


def _load_bundle(path, label):
    try:
        bundle = json.loads(pathlib.Path(path).read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise FormatError(f"{label} {path}: {e}") from None
    errs = check_bundle_schema(bundle)
    if errs:
        raise FormatError(f"{label} {path} is not a valid bundle:\n  " + "\n  ".join(errs))
    return bundle


def _write(path, text):
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def _bundle_text(bundle):
    return json.dumps(bundle, indent=1, ensure_ascii=False) + "\n"


def _report_build(result):
    for w in result.warnings:
        _err(f"warning: {w}")
    for e in result.errors:
        _err(f"error: {e}")


def cmd_build(a):
    previous = _load_bundle(a.previous, "previous bundle") if a.previous else None
    res = build(a.config, previous=previous, baseline_id=a.baseline_id, commit=a.commit)
    _report_build(res)
    if res.errors:
        _err(f"build failed: {len(res.errors)} error(s)")
        return EXIT_ERRORS
    _write(a.out, _bundle_text(res.bundle))
    print(f"wrote {a.out}: {len(res.bundle['entities'])} entities, {len(res.bundle['links'])} links, "
          f"{len(res.bundle['artifacts'])} artifacts")
    if a.html:
        _write(a.html, render(res.bundle, evaluate(res.bundle), warnings=res.warnings))
        print(f"wrote {a.html}")
    return EXIT_OK


def cmd_check(a):
    baseline = _load_bundle(a.baseline, "baseline bundle") if a.baseline else None
    warnings = []
    if a.bundle:
        bundle = _load_bundle(a.bundle, "bundle")
        errs = check_references(bundle, root=a.root) if a.root else check_references(bundle)
        if errs:
            for e in errs:
                _err(f"error: {e}")
            return EXIT_ERRORS
    else:
        res = build(a.config, previous=baseline, baseline_id=a.baseline_id, commit=a.commit)
        _report_build(res)
        if res.errors:
            _err(f"build failed: {len(res.errors)} error(s)")
            return EXIT_ERRORS
        bundle, warnings = res.bundle, res.warnings
        if a.out:
            _write(a.out, _bundle_text(bundle))
            print(f"wrote {a.out}")

    gaps = evaluate(bundle)
    if baseline is not None:
        new, _existing, fixed = ratchet(gaps, evaluate(baseline))
        new_ids = {g.id for g in new}
    else:
        new, fixed, new_ids = gaps, [], None

    for g in gaps:
        marker = "" if new_ids is None else ("NEW  " if g.id in new_ids else "base ")
        print(f"{marker}rule {g.rule}: {g.message}")
    for g in fixed:
        print(f"fixed rule {g.rule}: {g.message}")

    failing = new if baseline is not None else gaps
    status = "fail" if failing else "pass"
    summary = f"{len(gaps)} gap(s)"
    if baseline is not None:
        summary += f", {len(new)} new, {len(fixed)} fixed since baseline"
    print(f"{status.upper()}: {summary}")

    if a.html:
        _write(a.html, render(bundle, gaps, new_ids=new_ids, fixed=fixed, warnings=warnings))
        print(f"wrote {a.html}")
    if a.json:
        _write(a.json, json.dumps({
            "status": status, "gaps": [g.as_dict() for g in gaps],
            "new": sorted(new_ids) if new_ids is not None else None,
            "fixed": [g.as_dict() for g in fixed],
        }, indent=1) + "\n")
        print(f"wrote {a.json}")
    return EXIT_GAPS if failing else EXIT_OK


def cmd_report(a):
    bundle = _load_bundle(a.bundle, "bundle")
    baseline = _load_bundle(a.baseline, "baseline bundle") if a.baseline else None
    gaps = evaluate(bundle)
    if baseline is not None:
        new, _e, fixed = ratchet(gaps, evaluate(baseline))
        html = render(bundle, gaps, new_ids={g.id for g in new}, fixed=fixed)
    else:
        html = render(bundle, gaps)
    _write(a.out, html)
    print(f"wrote {a.out}")
    return EXIT_OK


def cmd_validate(a):
    errors, std = [], None
    if a.standard:
        std, e = check_standard(a.standard)
        errors += e
        print(f"standard   {a.standard}: {'ok' if not e else f'{len(e)} error(s)'}")
        if e:
            std = None
    if a.requirements:
        e, n = check_requirement_files(a.requirements)
        errors += e
        print(f"reqfiles   {n} file(s): {'ok' if not e else f'{len(e)} error(s)'}")
    if a.bundle:
        bundle = json.loads(pathlib.Path(a.bundle).read_text())
        e = check_bundle_schema(bundle)
        if not e:
            e = check_references(bundle, std, a.standard if std else None, a.root)
        errors += e
        print(f"bundle     {a.bundle}: {'ok' if not e else f'{len(e)} error(s)'}")
    for e in errors:
        _err(f"error: {e}")
    return EXIT_ERRORS if errors else EXIT_OK


def main(argv=None):
    ap = argparse.ArgumentParser(prog=GENERATOR, description="Requirements traceability and certification evidence.")
    ap.add_argument("--version", action="version", version=f"{GENERATOR} {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def build_args(p):
        p.add_argument("-c", "--config", default="reqthread.yaml", help="project config (default: reqthread.yaml)")
        p.add_argument("--baseline-id", help="baseline id (default: git tag or commit)")
        p.add_argument("--commit", help="commit hash (default: git HEAD)")

    p = sub.add_parser("build", help="build an evidence bundle")
    build_args(p)
    p.add_argument("-o", "--out", default="bundle.json")
    p.add_argument("--previous", help="previous baseline's bundle, to chain hashes")
    p.add_argument("--html", help="also write an HTML report")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("check", help="build (or load) a bundle and evaluate gate rules; exit 2 on gaps")
    build_args(p)
    p.add_argument("--bundle", help="check an existing bundle instead of building")
    p.add_argument("--root", help="with --bundle: verify artifact hashes under this directory")
    p.add_argument("--baseline", help="baseline bundle: fail only on gaps not already present in it")
    p.add_argument("-o", "--out", help="write the built bundle here")
    p.add_argument("--html", help="write an HTML report")
    p.add_argument("--json", help="write a JSON gap report")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("report", help="render an HTML report from a bundle")
    p.add_argument("--bundle", required=True)
    p.add_argument("--baseline")
    p.add_argument("-o", "--out", default="report.html")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("validate", help="validate format files (standard data, requirement files, a bundle)")
    p.add_argument("--standard")
    p.add_argument("--requirements")
    p.add_argument("--bundle")
    p.add_argument("--root")
    p.set_defaults(func=cmd_validate)

    a = ap.parse_args(argv)
    try:
        return a.func(a)
    except FormatError as e:
        _err(f"error: {e}")
        return EXIT_ERRORS


if __name__ == "__main__":
    sys.exit(main())
