# reqthread

> The golden thread from requirement to evidence.

Traceability and certification evidence for safety-critical embedded software. It reads what your repo
already has — requirements as files, `@satisfies` / `@verifies` annotations in code and tests, and the
JUnit, coverage, and SARIF output your CI already produces — and builds a hashed evidence bundle, checks
it against gate rules, and writes a standalone HTML report.

It fails your pipeline when a requirement loses its test, a test verifying a safety requirement fails or
never runs, code traces to nothing, or a static-analysis finding is open. With a baseline, it fails only
on **new** gaps, so a team with existing gaps can adopt it today.

Standard-agnostic by design: integrity levels, test levels, tool classes, and package sections come from
a **standard-data file you load from your own licensed copy**. The tool ships no standard text. A
structure-only IEC 61508-3 skeleton is in `standards/`.

## Install

```
pip install git+https://github.com/eggheadengineer/reqthread
```

Python 3.10 or later. Two dependencies: PyYAML and jsonschema. A PyPI release (`pip install reqthread`) is coming.

## Quick start

```
git clone https://github.com/eggheadengineer/reqthread && cd reqthread
pip install .
reqthread check -c examples/wb55-ref/reqthread.yaml --html report.html
```

`examples/wb55-ref/` is a real reference project — a black-channel heartbeat receiver in C, tested from
pytest, with real gcov coverage and real flawfinder SARIF. It has three genuine gaps; the report shows them.

## Annotate code and tests

```c
/* @satisfies SSR-001
 * @implements DD-TIMEOUT */
bool hb_supervise(hb_state_t *s, uint32_t now_ms) { … }
```

```python
def test_trip_after_300ms(lib):
    """@verifies SSR-001"""
```

A tag applies to the function it is inside, or the function directly below it. A block containing
`@file` applies to the whole file. Anything ambiguous is an **error**, never a guess. Zephyr `ZTEST`,
GoogleTest `TEST`, Unity `test_*`, and pytest tests are recognised.

## Commands

| Command | Does | Exit |
| --- | --- | --- |
| `reqthread check` | build, evaluate gates, optionally ratchet with `--baseline`; write `-o` bundle, `--html`, `--json` | 0 pass · 1 error · 2 gaps |
| `reqthread build` | build and write a bundle (`--previous` chains hashes) | 0 · 1 |
| `reqthread report` | render HTML from a bundle | 0 · 1 |
| `reqthread hazards` | hazard analysis on its own: validate hazard and cause files, print the hazard matrix | 0 · 1 · 2 gaps |
| `reqthread validate` | validate standard data, requirement files, or a hand-written bundle | 0 · 1 |

## Gate rules

1. Every software safety requirement has a verifying test at each declared test level.
2. Every software safety requirement derives from a system-level requirement.
3. Every code unit traces to a requirement or design element, or is marked `@infrastructure` with a reason.
4. Every test verifying a safety requirement **passed** at baseline and failed nowhere — skipped or never-run doesn't count.
7. Every static-analysis finding is fixed or covered by an unexpired, approved deviation.
11. Every hazard is mitigated by at least one requirement, directly or through one of its causes.
12. Every cause (STPA unsafe control action or FMEA failure mode) is mitigated by a requirement, or its residual risk is formally accepted.
13. Every requirement that mitigates a hazard is a safety requirement with an integrity level.

## Hazard analysis

Hazards and causes live in the repo as files too, so the trace runs from hazard to cause to requirement to test to CI result. In the reference project, HAZ-001 (machine keeps moving after a stop command) traces through three unsafe control actions to SSR-001..003, and a fourth cause, a stuck-high output driver, has no mitigating requirement. The hazard analysis found a gap the requirements never knew about.

```
reqthread hazards --hazards hazards/ --causes causes/ --requirements requirements/
```

That command needs no project config, standard data, or CI output, so a safety engineer can start with hazard analysis alone and add the rest later.

## CI

- **GitHub:** `ci/github/action.yml` (composite action)

  ```yaml
  permissions: { contents: read, actions: read }   # actions: read lets PR runs fetch the baseline
  jobs:
    traceability:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@v7
        - uses: eggheadengineer/reqthread/ci/github@main   # pin a release tag once v0.1.0 is out
          with:
            config: reqthread.yaml
  ```
- **GitLab:** `templates/reqthread.yml` (CI/CD component)

Both record the default branch's bundle as the baseline and fail merge requests only on new gaps.
The GitHub Action has been exercised end to end on GitHub-hosted runners; the GitLab component has not run yet.

## Docs

- `docs/FORMATS.md` — file formats, annotations, bundle model
- `docs/EVIDENCE_PACKAGE_SPEC.md` — what an IEC 61508-3 assessor expects, and what this automates

## Tests

```
PYTHONPATH=src python3 -m unittest discover -s tests
```

## License

Apache-2.0. See `LICENSE`.
