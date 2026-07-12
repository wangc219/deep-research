# Phase 2 Task 1 Report

## Result

Implemented load-time agent registry validation and configurable baseline-agent
replacement on the current `main` branch. The change stays within the four
owned files and does not modify or stage `tests/test_responses_adapter.py`.

## Files

- `src/equipment_deep_research/agents/contracts.py`
- `src/equipment_deep_research/agents/registry.py`
- `tests/equipment_deep_research/unit/test_agent_registry.py`
- `.superpowers/sdd/phase-2-task-1-report.md`

## Design

- Added a declarative catalog for tool names, named contracts, visible context
  sections, and readable/writable object scopes. It contains no handlers or
  executable tool-registry behavior, so Phase 2 Task 2 can attach execution
  without coupling agent configuration to runtime objects.
- `AgentDef.validate()` now validates safe identifiers, non-empty capability
  tags, declared tool names, input/output contracts, visible sections, object
  scopes, and model profiles.
- Named contracts are checked against the catalog. Existing non-empty inline
  mapping contracts remain supported; mappings that name/reference a contract
  are checked against the same catalog.
- `model_profile` defaults to serializable
  `{"provider": "responses", "model": "gpt-5.5"}` and rejects secret-bearing
  fields such as API keys, authorization values, credentials, headers, secrets,
  and tokens.
- Default baseline selection is declarative through `system_agent`. The three
  Phase 1 system IDs (`winning_mechanism`, `auditor`, and `reporter`) retain
  compatibility through load-time legacy defaults. Explicit requested IDs can
  still select a system agent for its dedicated orchestration stage.
- `resolve_capability()` deterministically returns the first selected agent
  declaring a requested capability and raises `KeyError` when none exists.
- Existing direct `AgentDef(...)` callers remain compatible through defaults
  for contracts, model profile, scopes, and system role.

## TDD Evidence

### RED 1

Command:

```text
python3 -m pytest tests/equipment_deep_research/unit/test_agent_registry.py -q
```

Observed result before implementation:

```text
10 failed in 0.06s
```

The failures showed missing duplicate detection, named-contract support,
declaration validation, system-role filtering, model profiles,
`resolve_capability()`, and `AgentDef.validate()`.

### GREEN 1

Command:

```text
python3 -m pytest tests/equipment_deep_research/unit/test_agent_registry.py -q
```

Observed result:

```text
10 passed in 0.03s
```

### RED 2: Self-review contract-reference case

Command:

```text
python3 -m pytest tests/equipment_deep_research/unit/test_agent_registry.py::test_registry_rejects_duplicate_ids_and_unknown_contract -q
```

Observed result before tightening inline contract validation:

```text
1 failed in 0.03s
```

The failing case demonstrated that `{name: missing_contract}` could otherwise
bypass named-contract existence checks.

### GREEN 2

Command:

```text
python3 -m pytest tests/equipment_deep_research/unit/test_agent_registry.py -q
```

Observed result:

```text
10 passed in 0.03s
```

## Requested Regression Tests

Command:

```text
python3 -m pytest tests/equipment_deep_research -q -k "custom_agent or registry"
```

Observed result:

```text
21 passed, 251 deselected in 0.09s
```

Additional focused compatibility checks:

```text
python3 -m pytest tests/equipment_deep_research/unit/test_configuration.py -q
12 passed in 0.03s

python3 -m pytest tests/test_deep_research_runner.py -q -k "custom_agent or tool_permission or scheduler_revalidates"
3 passed, 20 deselected in 0.08s
```

## Final Verification

```text
python3 -m pytest tests/equipment_deep_research -q
272 passed in 2.02s

python3 -m pytest tests/test_deep_research_runner.py -q
23 passed in 0.36s

git diff --check
clean

python3 -m compileall -q src/equipment_deep_research/agents tests/equipment_deep_research/unit/test_agent_registry.py
clean
```

All tests were local and used no network access. No Codex CLI call was added or
made by the implementation.

## Self-review

- Confirmed the change does not implement Task 2 executable tool behavior.
- Confirmed checked-in Phase 1 `agents.yaml` loads with the new validation.
- Confirmed custom multi-capability agents replace the default baseline set.
- Confirmed system agents are excluded only from default baseline selection.
- Confirmed model profiles remain plain serializable data without API keys or
  headers.
- Confirmed existing direct constructors and structured Phase 1 runtime tests
  remain green.
- Confirmed unrelated and untracked work remains untouched.

## Concerns

None.
