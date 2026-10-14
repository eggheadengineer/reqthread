# Formats

**Version 0.1.0.** All formats are name-neutral (URN ids; the generator name is data), so the product can be renamed without a migration. Schemas live in `src/reqthread/schema/` and ship inside the package.

| Format | Schema | Authored by | Purpose |
| --- | --- | --- | --- |
| Project config `reqthread.yaml` | `config.schema.json` | the team | Where everything is: items, sources, tests, CI inputs, environments, people, tools |
| Requirement file `*.req.md` | `requirement.schema.json` | the team | One requirement per file, reviewed like code |
| Architecture file `*.arch.md` | `architecture.schema.json` | the team | One architecture element per file |
| Design file `*.design.md` | `design.schema.json` | the team | One design element per file |
| Deviation register `deviations.yaml` | `deviations.schema.json` | the team | Approved, expiring justifications for static-analysis findings |
| Standard data `*.yaml` | `standard-data.schema.json` | the licensee, from their own copy | Integrity levels, sections, test levels, tool classes, routes, techniques, coverage targets |
| Evidence bundle `bundle.json` | `bundle.schema.json` | generated | One baseline's trace graph, verification records, and artifact manifest |

Two examples: `examples/wb55-ref/` is a real project the tool builds from source; `examples/reference/bundle.json` is a hand-written bundle exercising the model directly (`reqthread validate`).

## Design principles

- **Bring your own standard.** Everything standard-specific is customer-loaded data. A bundle records the hash of the standard data it was checked against.
- **Fields express ownership and measurement; links express traceability.** A test result *belongs to* a test (field); a test *verifies* a requirement (link). Gate rules walk links.
- **Ids are `<prefix>:<local>`** and deterministic: the same inputs always produce the same ids, so bundles diff cleanly and gaps ratchet stably. Findings use the tool's fingerprint when it provides one, because line numbers move with unrelated edits.
- **Everything hashed.** Artifacts carry the sha256 of their bytes. Each baseline records `previous_bundle_hash`, chaining baselines into a tamper-evident history. The canonical hash is sorted-key compact JSON; bundles are float-free with ASCII keys, which makes this identical to RFC 8785 (floats are rejected to keep it so).
- **Ambiguity is an error, never a guess** — in annotation attribution, in JUnit matching, in key resolution. A wrong trace link is worse than a missing one.

## Project config

```yaml
version: 1
project: { id: wb55-black-channel, name: "…", integrity_claim: SIL3 }
standard: ../../standards/iec61508-3.skeleton.yaml      # paths are relative to this file

requirements: { paths: [requirements], section: 02_software_safety_requirements }
architecture: { paths: [architecture], section: 04_architecture }
design:       { paths: [design],       section: 05_detailed_design }

sources:
  - { glob: "src/**/*.c", language: c }
tests:
  - { glob: "tests/module/**/*.py", language: python, level: module }
  - { glob: "tests/hil/**/*.py",    language: python, level: pe_integration }

environments:
  - { id: host,        name: host-x86_64,   env_type: host }
  - { id: target-wb55, name: nucleo_wb55rg, env_type: target, board: nucleo_wb55rg }

ingest:   # each input is hashed into the manifest under its section
  - { type: junit,  path: ci-out/junit-module.xml, environment: host, section: 07_module_testing }
  - { type: junit,  path: ci-out/junit-hil.xml,    environment: target-wb55, section: 09_pe_integration, optional: true }
  - { type: lcov,   path: ci-out/coverage.lcov,    environment: host, test_level: module, section: 07_module_testing }
  - { type: sarif,  path: ci-out/flawfinder.sarif, section: 06_code }
  # also: cobertura

deviations: { path: deviations.yaml, section: 06_code }
people: [ { id: reviewer-a, name: "…", roles: [safety_reviewer] } ]
tools:  [ { id: gcc, name: gcc, version: "13.3.0", class: T3 } ]
preexisting: [ { id: zephyr, name: zephyr, version: v4.2.0, route: "3S" } ]
```

## Item files

One item per file, named `<ID>.<kind>.md`. YAML front matter, then a `# Title`. For requirements, text up to an optional `## Rationale` heading is the requirement text.

```markdown
---
id: SSR-001
level: software            # system | software | derived
type: integrity            # functional | integrity
integrity_level: SIL3
derives_from: [SYS-004]
allocated_to: [ARCH-RX]
verification: [test]       # test | analysis | review | inspection | demonstration
test_levels: [module, pe_integration]
status: approved           # draft | approved | retired
---
# Heartbeat supervision timeout

The receiver shall de-energise the machine-enable output within 300 ms of the last valid heartbeat frame.

## Rationale
…
```

Architecture front matter: `id`, `safety_related`, optional `integrity_level`. Design front matter: `id`, optional `derives_from` (architecture keys) and `satisfies` (requirement keys).

## Annotations

| Tag | Valid in | Meaning |
| --- | --- | --- |
| `@satisfies KEY[, KEY…]` | sources | satisfies requirement(s) |
| `@implements KEY[, KEY…]` | sources | implements design or architecture element(s) |
| `@infrastructure reason…` | sources | deliberately untraced; the reason may continue on following lines until a blank line or another tag |
| `@verifies KEY[, KEY…]` | tests | verifies requirement(s) or design/architecture element(s) |
| `@test-level LEVEL` | tests | override the level from the test glob |
| `@file` | both | the other tags in this block apply to the whole file |

**Attribution:** a tag block applies to the innermost function enclosing it; otherwise to the function directly below it, with only blank lines, comments, preprocessor lines or decorators between. In tests, `@file` tags are inherited by every test in the file, and class docstring tags by every test method. Anything else — a tag above a global, a module docstring without `@file`, `@verifies` on a helper — is an error.

**Recognised:** C/C++ functions (including return types on their own line and function-pointer parameters); Zephyr `ZTEST`/`ZTEST_F`/`ZTEST_USER*`, GoogleTest `TEST`/`TEST_F`/`TEST_P` (symbol `suite.name`); Unity-style `test_*` functions; Python functions, methods, and pytest tests (functions named `test*`, methods of `Test*` classes).

**JUnit matching:** `classname.name` against the test's dotted path (pytest), then the symbol, then a unique last name component. Parametrised cases aggregate (error > fail > pass > skip). Ambiguous matches are reported as unmatched, never assigned.

## Deviation register

```yaml
- key: DEV-001
  match: { tool: flawfinder, rule: FF1004, path: src/frame_auth.c }   # optional: line, fingerprint
  justification: …
  scope: …
  approved_by: reviewer-a       # a person id from the config
  approved_at: 2026-10-13T15:00:00Z
  expires_at: 2027-04-30        # null for no expiry
```

A finding suppressed in source (SARIF `suppressions`) with no matching deviation stays **open**: an in-source suppression is not a recorded justification. A deviation that matches nothing is reported as stale.

## Bundle model

Entity kinds and prefixes: requirement `req:`, architecture_element `arch:`, design_element `design:`, code_unit `code:`, test_case `test:`, environment `env:`, test_result `result:`, coverage_record `cov:`, finding `finding:`, deviation `dev:`, review `review:`, tool `tool:`, preexisting_element `pre:`, technique_status `tech:`, change `change:`, person `person:`.

| Link | From → To |
| --- | --- |
| `derives_from` | requirement → requirement; design_element → architecture_element |
| `allocated_to` | requirement → architecture_element |
| `satisfies` | design_element or code_unit → requirement |
| `implements` | code_unit → design_element or architecture_element |
| `verifies` | test_case → requirement, design_element or architecture_element |
| `covers` | test_case → code_unit |
| `justifies` | deviation → finding |
| `reviews` | review → requirement, architecture, design, code, test, or change |
| `affects` | change → requirement, architecture, design, code, or test |
| `supersedes` | requirement → requirement |

Code units are created for **every** function in the source globs, not only annotated ones — otherwise untraced code would be invisible. A file-level unit (symbol `null`) exists when a file carries `@file` tags; it traces every function in that file for rule 3. Coverage is attributed per function by line range.

## Gate rules and ratcheting

Rules 1–4 and 7 (see README). Each gap has a stable id, e.g. `rule1:req:SSR-003:module`. `check --baseline previous.json` re-evaluates the baseline bundle and fails only on gaps whose ids are not in it, listing fixed gaps separately.

## Versioning

`bundle_format` and `data_format` are semver. Minor versions are additive; readers accept any minor of a major they know and reject unknown majors.

## Known limits

- **C++:** template return types (`std::vector<int> f()`), and attributes before the storage class (`__attribute__((x)) static void f()`), are not yet recognised as functions. Methods defined inside a class body get the bare method name.
- **Independence levels** per integrity level aren't in standard data yet; review records and rule 10 come with merge-request ingestion.
- **technique_status** is modeled but not populated by the builder yet.
- **Multi-repo projects** and **StrictDoc `.sdoc` import** are not modeled.
