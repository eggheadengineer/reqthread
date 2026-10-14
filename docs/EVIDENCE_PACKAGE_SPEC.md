# IEC 61508-3 evidence package

What an assessor expects to receive for the software of a safety-related system, what satisfies each item, where small teams usually fall short, and how much of it reqthread can produce.

## Read this first

- **Written from working knowledge of IEC 61508:2010 (edition 2).** Items marked **[verify]** should be checked against your licensed copy. Clause structure can be confirmed from the free table-of-contents previews on the IEC webstore.
- **Bring your own standard data.** reqthread ships no standard text. Clause references and technique recommendation levels are data your organisation loads from its own licensed copy (`standards/` has a structure-only skeleton). This keeps IEC copyright out of the tool and makes other standards — ISO 26262, IEC 62304 — a data change rather than a code change.
- **Edition watch.** IEC 61508 edition 3 has been in development; a restructured part 3 would move the clause numbers referenced here.
- "Evidence" throughout means three things together: the **work product**, a **verification record** showing it was checked by someone with the required independence, and **traceability** linking it to what it came from and what depends on it. A document without the other two is not evidence.

## How the assessor reads a package

The functional safety assessment (61508-1 clause 8) asks whether the lifecycle was followed and whether the evidence supports the claimed SIL. In practice an assessor works through the package looking for four things in every phase:

1. The work product exists and is under configuration control at an identified baseline.
2. It was verified, by someone independent enough for the SIL, and that verification is recorded.
3. It traces backward to its source and forward to what implements and tests it.
4. Techniques were chosen per the Annex A/B tables for the SIL, and any Highly Recommended technique not used has a written justification.

Most findings against small teams are failures of items 2–4, not item 1. They usually *did* the work; they can't *show* it was verified, traced, and technique-justified.

## Package layout

One package per baseline. Every file content-hashed in the manifest; the manifest chains to the previous baseline's manifest hash, so the package history is tamper-evident.

```
evidence/<product>-<baseline>/
  00_index.md                     reading guide, scope, SIL claim, manifest summary
  manifest.json                   every artifact: path, hash, generator, version, source commit
  01_management/                  FSM plan, roles, competence records, CM plan
  02_software_safety_requirements/
  03_validation_plan/
  04_architecture/
  05_detailed_design/
  06_code/                        coding standard, deviation register, static analysis
  07_module_testing/
  08_integration_testing/
  09_pe_integration/
  10_validation/
  11_verification/                verification report per phase
  12_traceability/                matrices both directions, gap report
  13_modification/                changes since previous baseline, impact analyses
  14_tools/                       tool register, T2/T3 classification and evidence
  15_preexisting_software/        RTOS, libraries, SOUP: compliance route and justification
  16_techniques/                  Annex A/B technique selection and justification
```

## Automation levels used below

| Level | Meaning |
| --- | --- |
| **AUTO** | reqthread generates it entirely from the repo and CI output |
| **ASSIST** | reqthread generates the skeleton, checks completeness, flags gaps; a human writes the substance |
| **INDEX** | outside reqthread's scope; it only places, hashes, and cross-references the artifact |

---

## Phase by phase

### 01 — Functional safety management (61508-1 cl. 6; 61508-3 cl. 6)

| Work product | Assessor looks for | reqthread | Where small teams fail |
| --- | --- | --- | --- |
| FSM plan | Lifecycle defined, responsibilities named, verification and assessment planned up front | INDEX | Written retroactively, or a generic template never tailored |
| Roles and competence records | Named people, evidence their competence fits their role | ASSIST — checks every reviewer/approver in the package has a competence record | Missing entirely; "everyone's senior" is not a record |
| Configuration management plan | How items are identified, baselined, changed, released | ASSIST — derives CM identification from git and CI | Cannot reproduce the released binary from a tagged commit |

### 02 — Software safety requirements specification (61508-3 7.2)

| Work product | Assessor looks for | reqthread | Where small teams fail |
| --- | --- | --- | --- |
| SSRS | Each safety requirement uniquely identified, unambiguous, verifiable, with SIL, derived from system safety requirements | ASSIST — parses requirement files, enforces IDs, SIL attribute, verification method, source link | Safety requirements mixed into general requirements with no distinction |
| Safety integrity requirements | Not just functions — response times, diagnostics, behaviour on detected fault, safe state | ASSIST — requirement type field; gap rule if a function has no associated integrity requirement | Functional requirements present, integrity requirements absent |
| SSRS review record | Verified against system safety requirements with required independence | AUTO — from merge request approvals (see Verification) | Reviewed in a meeting, nothing recorded |
| Backward trace | Every SSR traces to a system-level safety requirement or hazard | AUTO | Requirements with no stated source |

### 03 — Validation plan for software (61508-3 7.3)

| Work product | Assessor looks for | reqthread | Where small teams fail |
| --- | --- | --- | --- |
| Software validation plan | Written **before** validation, defines how each SSR will be validated, pass criteria, environment | ASSIST — skeleton generated from SSRS; flags SSRs with no planned validation; records plan baseline date | Plan written after testing, or dated after the tests it describes |

The plan-before-test ordering is checkable from git history. reqthread should flag any validation test whose first commit predates the plan baseline that covers it.

### 04 — Software architecture (61508-3 7.4.3)

| Work product | Assessor looks for | reqthread | Where small teams fail |
| --- | --- | --- | --- |
| Architecture description | Decomposition into elements, which are safety-related, how safety and non-safety parts are separated, how SSRs are allocated | ASSIST — architecture elements as identified entities; allocation links to SSRs | Block diagram with no allocation of requirements to elements |
| Freedom from interference argument | If mixed-criticality, how non-safety code is prevented from corrupting safety code — spatial (MPU), temporal (scheduling, watchdog), data | INDEX, plus a gap rule: mixed-SIL architecture requires a linked FFI argument | Asserted, not argued |
| Architecture technique justification | Annex A table for architecture design [verify table A.2] | ASSIST — see Techniques | HR techniques silently skipped |
| Review record | Architecture verified against SSRS | AUTO | Not recorded |

### 05 — Detailed design (61508-3 7.4.5)

| Work product | Assessor looks for | reqthread | Where small teams fail |
| --- | --- | --- | --- |
| Module design | Each module's interface, behaviour, and the SSRs it supports | ASSIST — design elements traceable to architecture elements and SSRs | Design exists only as code |
| Review record | Design verified against architecture | AUTO | Not recorded |

Small teams frequently collapse detailed design into well-commented code. Whether that is acceptable is a judgment the assessor makes against the SIL. reqthread should not pretend to resolve it; it should make the choice explicit in the package and link the justification.

### 06 — Code implementation (61508-3 7.4.6)

| Work product | Assessor looks for | reqthread | Where small teams fail |
| --- | --- | --- | --- |
| Coding standard | Declared language subset, e.g. MISRA C:2012, with project-specific rules | INDEX | Declared, not enforced |
| Static analysis results | Standard enforced by tool, results at baseline | AUTO — ingests SARIF | Run occasionally, not at baseline |
| Deviation register | Every finding fixed or deviated, each deviation justified, approved, and scoped | AUTO for state; ASSIST for justification workflow; gap rule on unexpired approval | Suppressions in code with no recorded justification |
| Code review records | Each change reviewed with required independence | AUTO — from merge requests | Reviews happen, approvals are rubber-stamp or self-approved |
| Backward trace | Every code unit traces to a design element or SSR — no unexplained code | AUTO — from annotations; untraced units flagged unless marked infrastructure with a reason | Only forward trace exists; assessor finds code nobody can justify |

### 07 — Module testing (61508-3 7.4.7)

| Work product | Assessor looks for | reqthread | Where small teams fail |
| --- | --- | --- | --- |
| Module test specification | Tests defined against design, with expected results | ASSIST — test cases as entities linked to design elements and SSRs | Tests exist, specification doesn't |
| Module test results | All tests run at baseline, results recorded, failures dispositioned | AUTO — ingests JUnit XML | Results not retained per baseline |
| Structural coverage | Coverage achieved against the SIL target, with gaps justified | AUTO — ingests gcov/lcov/Cobertura per test level and environment | Coverage measured on host with no argument for target equivalence; uncovered code unexplained |

**Coverage targets by SIL [verify against Annex B dynamic-analysis table].** Working understanding for 2010 edition: 100% statement coverage highly recommended from SIL 2; 100% branch coverage highly recommended at SIL 3 and 4; MC/DC highly recommended at SIL 4 only. Treat these as placeholders until checked. Whatever the numbers, the product requirement is the same: every uncovered statement or branch either gets covered or gets a recorded justification, and the package shows which.

### 08 — Integration testing (61508-3 7.4.8)

| Work product | Assessor looks for | reqthread | Where small teams fail |
| --- | --- | --- | --- |
| Integration test specification | Tests against architecture: interfaces, data and control flow between elements | ASSIST — tests linked to architecture elements | Integration testing is "the system test" |
| Integration test results | At baseline, failures dispositioned | AUTO | Same as module |

### 09 — Programmable electronics integration (61508-3 7.5)

| Work product | Assessor looks for | reqthread | Where small teams fail |
| --- | --- | --- | --- |
| HW/SW integration tests | Software running on target hardware meets SSRs, including diagnostics and safe-state behaviour | ASSIST — environment attribute on test results distinguishes target from host; gap rule if an SSR is verified on host only | All verification on host or emulator, none on target |

This is where hardware-in-the-loop results land. A HIL rig emitting JUnit XML tagged with a target environment ID is all reqthread needs.

### 10 — Software aspects of system safety validation (61508-3 7.7)

| Work product | Assessor looks for | reqthread | Where small teams fail |
| --- | --- | --- | --- |
| Validation results | Every SSR validated per the plan, results against stated pass criteria | AUTO for results-against-plan; gap rule on any SSR planned but not validated | Validation results exist but don't map to the plan |

### 11 — Verification (61508-3 7.9)

Verification is not a phase at the end; it is a record attached to every phase.

| Work product | Assessor looks for | reqthread | Where small teams fail |
| --- | --- | --- | --- |
| Verification report per phase | Each phase's outputs checked against its inputs, by whom, with what result | ASSIST — generated from review records, test results, and trace completeness for that phase | One "verification report" at the end covering everything vaguely |
| Independence evidence | Reviewer independence appropriate to the SIL [verify independence requirements in 61508-1 cl. 8] | AUTO — author ≠ approver; approver's role and competence record checked | Self-review, or reviewer is the author's direct collaborator with no stated independence |

**Merge requests are verification records that most small teams already have and don't present.** A GitLab MR with a named author, named approvers, a linked requirement ID, a diff, CI results, and a timestamp contains nearly everything a review record needs. reqthread's single highest-leverage automation is turning MR approval history into phase-tagged verification records with independence checks.

### 12 — Traceability (throughout 61508-3 7.x)

| Work product | Assessor looks for | reqthread | Where small teams fail |
| --- | --- | --- | --- |
| Forward trace | System safety req → SSR → architecture → design → code → tests → results | AUTO | Partial chains |
| Backward trace | Every downstream item traces back to a requirement | AUTO | Missing entirely |
| Gap report | No orphans, no untested SSRs, no unjustified code | AUTO — the core OSS deliverable | Not produced; gaps found by the assessor |

### 13 — Modification (61508-3 7.6 and 7.8)

| Work product | Assessor looks for | reqthread | Where small teams fail |
| --- | --- | --- | --- |
| Change records since previous baseline | Every change identified, authorised | AUTO — from git between baseline tags and linked MRs | Changes after the "certified" baseline with no record |
| Impact analysis | For each change: affected requirements, design, code, tests; what was re-verified | AUTO for the affected-item set from the trace graph; ASSIST for the human judgment | Re-ran "the tests" without showing which were affected or why that set suffices |

Impact analysis falls almost directly out of the trace graph and is painful to do by hand.

### 14 — Support tools (61508-3 7.4.4; tool classes defined in 61508-4)

| Work product | Assessor looks for | reqthread | Where small teams fail |
| --- | --- | --- | --- |
| Tool register | Every off-line tool used, with exact version | AUTO — harvested from CI environment and lockfiles | Compiler version not pinned |
| Tool classification | Each tool classed T1, T2, or T3 | ASSIST — register with class field; gap rule on unclassified tools | Never classified |
| T2/T3 evidence | Specification or documentation, plus evidence of confidence: validation, proven in use, or assessment [verify sub-clauses 7.4.4.4 onward] | INDEX — links vendor qualification kits and in-house validation | Compiler and test tools treated as trustworthy by default |

Working definitions [verify against 61508-4]: **T1** generates nothing that can contribute to executable code (editors, requirements tools without code generation). **T2** supports test or verification; an error could fail to reveal a defect but cannot directly create one (test harnesses, coverage tools, static analysers). **T3** produces output that can directly or indirectly contribute to executable code (compilers, code generators).

**reqthread itself is almost certainly T2.** If its gap rules wrongly report "every SSR is tested," a defect could go unrevealed. That is why reqthread needs its own tool qualification evidence — and it means reqthread's own validation suite must be built to the same standard it checks. Dogfood the package spec on reqthread before selling it.

### 15 — Pre-existing software (61508-3 7.4.2.12 [verify])

| Work product | Assessor looks for | reqthread | Where small teams fail |
| --- | --- | --- | --- |
| Pre-existing element register | Every RTOS, library, and SOUP component with version | AUTO — from manifests, lockfiles, west.yml, submodules | Incomplete; transitive dependencies missed |
| Compliance route per element | Route 1S (developed compliantly), 2S (proven in use), or 3S (assessment of non-compliant development), with evidence | ASSIST — route field and justification link; gap rule on unrouted elements | No route stated; "it's widely used" offered as argument |
| Safety manual for compliant items | For elements claimed compliant, the supplier's safety manual and its constraints honoured [verify 61508-3 Annex D] | INDEX | Constraints in the supplier manual ignored |

**Zephyr is the live example.** Its safety effort targets Route 3S for a ~15K-line kernel scope, explicitly excluding drivers and BSPs. A team using Zephyr at SIL 3 today must justify the kernel themselves until that lands, and the drivers and BSP permanently. A register that surfaces exactly which Zephyr subsystems are in the build — and which fall outside any upstream safety scope — is something a Zephyr-shop customer would value immediately.

### 16 — Techniques (61508-3 Annexes A and B)

| Work product | Assessor looks for | reqthread | Where small teams fail |
| --- | --- | --- | --- |
| Technique selection per phase | For the claimed SIL, which techniques were applied, with evidence links | ASSIST — catalog of technique IDs; per-technique status: applied (evidence link) / not applied (justification) | HR techniques silently skipped |
| Justifications | For every HR technique not applied, a written reason why the alternative is adequate | ASSIST — gap rule: HR + not applied + no justification fails the gate | Missing |

Subject to the copyright constraint above: ship technique IDs and short names, not the tables.

---

## Automation map

| Package section | AUTO | ASSIST | INDEX |
| --- | --- | --- | --- |
| 01 Management | | competence, CM | FSM plan |
| 02 Requirements | review, backward trace | SSRS structure, integrity reqs | |
| 03 Validation plan | | plan skeleton, ordering check | |
| 04 Architecture | review | allocation, techniques | FFI argument |
| 05 Detailed design | review | design trace | |
| 06 Code | static analysis, deviation state, review, backward trace | deviation workflow | coding standard |
| 07 Module test | results, coverage | test spec | |
| 08 Integration test | results | test spec | |
| 09 PE integration | | target-vs-host gap rule | |
| 10 Validation | results vs plan | | |
| 11 Verification | independence checks | per-phase report | |
| 12 Traceability | all | | |
| 13 Modification | change records, affected set | impact judgment | |
| 14 Tools | register | classification | T2/T3 evidence |
| 15 Pre-existing | register | route + justification | supplier safety manuals |
| 16 Techniques | | selection + justification | |

**Honest read:** reqthread can fully generate perhaps a third of the package and structure most of the rest. Its value is not writing the safety argument — no tool can — but making the evidence for it continuous, linked, hashed, and gap-checked, so the human work is writing judgment rather than assembling paperwork.

## What small teams most often fail to produce

Practitioner knowledge, ranked by how likely each is to block an assessment. Treat as hypotheses for the reference project to test, not as sourced findings.

1. **Recorded verification with independence.** The review happened; the record didn't.
2. **Backward traceability.** Code and tests that can't be traced to a requirement.
3. **Tool classification**, especially compiler (T3) and test/coverage tools (T2).
4. **Justification for skipped HR techniques.**
5. **Impact analysis for post-baseline changes.**
6. **Pre-existing software routes**, especially the RTOS.
7. **Coverage justification** — target versus host, and unexplained gaps.
8. **Integrity requirements** distinct from functional ones.
9. **Validation plan dated before validation.**
10. **Reproducible baseline** — the released binary rebuilt from the tagged commit.

Every one of these except the substance of item 4 is detectable from the repo and CI. That is what reqthread automates.

## Data model implications

**Entities**

| Entity | Key attributes |
| --- | --- |
| Requirement | id, level (system / software / derived), type (functional / integrity), SIL, text, rationale, source, verification method, status |
| ArchitectureElement | id, safety-related (bool), SIL, description |
| DesignElement | id, parent architecture element |
| CodeUnit | file, symbol, annotations, infrastructure flag + reason |
| TestCase | id, level (module / integration / PE / validation), environment (host / target id) |
| TestResult | test, baseline, environment, outcome, timestamp |
| CoverageRecord | code unit, test level, environment, statement / branch / MC-DC |
| Finding | SARIF rule, location, state |
| Deviation | finding(s), justification, approver, expiry |
| Review | artifact, author, reviewers, outcome, timestamp, independence level, source (MR id) |
| Tool | name, version, class (T1/T2/T3), evidence link |
| PreexistingElement | name, version, route (1S/2S/3S), justification link |
| Technique | catalog id, status, evidence or justification |
| Change | id, MR, affected items, impact judgment |
| Person | id, roles, competence record link |
| Baseline | id, commit, timestamp, manifest hash, previous manifest hash |

**Link types:** `derives_from` · `allocated_to` · `satisfies` · `implements` · `verifies` · `covers` · `justifies` · `reviews` · `affects` · `supersedes`.

**First gate rules** (the OSS CLI's exit code)

1. Every software safety requirement has at least one `verifies` link at its required test level.
2. Every SSR has a `derives_from` link to a system-level source.
3. Every code unit traces back to a requirement or design element, or is flagged infrastructure with a reason.
4. No test linked to an SSR is failing at baseline.
5. No SSR is verified on host only when target verification is required.
6. Coverage meets the declared SIL target, or each gap has a justification.
7. Every static-analysis finding is fixed or covered by an unexpired deviation.
8. Every tool in the register has a class; every T2/T3 tool has an evidence link.
9. Every pre-existing element has a compliance route.
10. Every review of a safety artifact has author ≠ approver.

reqthread 0.1.0 enforces rules 1–4 and 7. The rest arrive with the data that feeds them.

## Known gaps

- Every **[verify]** above needs checking against a licensed copy of the standard.
- Whether system-level safety requirements (61508-1/-2 territory) are in scope, or treated as an external input.
- Import of StrictDoc's SDoc format, so teams already using it can adopt reqthread without converting.
