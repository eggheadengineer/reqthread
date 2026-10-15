# WB55 black-channel reference project

A small, real safety-shaped firmware project used to dogfood the tool: a receiver that authenticates
and sequences heartbeat frames and drops machine-enable 300 ms after the last valid one. The C code is
written to run on the P-NUCLEO-WB55 under Zephyr; for now it builds and tests on a Linux host.

**Everything in `ci-out/` comes from real tool runs** (`./make_fixtures.sh`): gcc `--coverage`,
pytest driving the C code through ctypes, gcovr, and flawfinder. The only edit is mechanical: the script
rewrites this checkout's absolute path to `/builds/wb55-ref`, as if the tools had run on a CI runner.

**Three gaps are expected, and all three are true:**

1. **SSR-003 (replay rejection) has no test.** `seq_check` *is* exercised — coverage shows it ran —
   but no test verifies the requirement. That is the difference between coverage and traceability.
2. **The HIL test has only ever been skipped.** The rig driver doesn't exist yet, so SSR-001 is
   verified on the host only. When the rig runs, its `pytest --junitxml` output goes in
   `ci-out/junit-hil.xml` and the config already ingests it.
3. **FM-001, a stuck-high output driver, has no mitigating requirement.** The hazard analysis in
   `hazards/` and `causes/` traces HAZ-001 through three unsafe control actions to SSR-001..003, but the
   hardware failure mode has no software requirement and no accepted-risk record. That is what hazard
   analysis is for: it found a gap the requirements never knew about.

```
reqthread check -c examples/wb55-ref/reqthread.yaml --html report.html
```

`frame_tag` uses a placeholder keyed checksum, **not cryptography** — it stands in for AES-CMAC on
the WB55's AES peripheral so the project builds anywhere.
