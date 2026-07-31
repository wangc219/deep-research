# Codex Demand Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an independent Codex-driven demand-discovery workflow that runs all roles through Codex and produces real workflow artifacts without modifying the existing Phase 5 main chain.

**Architecture:** Implement `knowledgegraph.demand_discovery.codex_workflow` as a separate runner. It may reuse existing domain models, source registry, report publisher, and artifact conventions, but it must not call or change `autonomous_research.py`, `research_loop.py`, `scheduler.py`, `agent_harness.py`, or network worker internals. `scripts/demand_discovery_autonomous_research.py` may dispatch `--mode codex` to the independent runner.

**Tech Stack:** Python standard library, Codex CLI subprocess invocation isolated inside the new module, existing `DomainStore`/domain dataclasses/source whitelist/report rendering, unittest.

---

### Task 1: Independent Codex Workflow Module

**Files:**
- Create: `src/knowledgegraph/demand_discovery/codex_workflow.py`
- Create: `tests/test_demand_discovery_codex_workflow.py`
- Modify: `src/README.md`

- [x] **Step 1: Write failing tests**

Create tests with a fake role runner that returns JSON for `planner`, `reader`, `judge`, `synthesizer`, `auditor`, and `reporter`. Assert:

- every role is called in workflow order;
- whitelist evidence is imported into `SourceRecord` and `EvidenceCard`;
- out-of-whitelist evidence is rejected or downgraded and not attached as report evidence;
- `JudgementReport`, `CandidateDemand`, `AuditReport`, and `DemandReport` are written;
- `round_summary.json`, `domain.jsonl`, `trace.jsonl`, and `report.md` exist.

- [x] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_demand_discovery_codex_workflow -v`

- [x] **Step 3: Implement minimal independent workflow**

Implement:

- `CodexWorkflowConfig`
- `CodexRoleRunner`
- `FakeCodexRoleRunner` test hook support through injected callable
- per-role prompt construction
- Codex CLI command construction local to this module, including `codex --search exec`
- JSON object extraction
- whitelist source validation through `SourceRegistry`
- importers for source/evidence/judgement/candidate/audit/report role outputs
- trace events for each role
- artifact writing to run dir

- [x] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_demand_discovery_codex_workflow -v`

### Task 2: CLI Dispatch Only

**Files:**
- Modify: `scripts/demand_discovery_autonomous_research.py`
- Modify: `tests/test_demand_discovery_autonomous_research_runner.py`
- Modify: `scripts/README.md`

- [x] **Step 1: Write failing CLI test**

Patch `run_codex_workflow_sync`, call the existing CLI with `--mode codex`, and assert the codex-specific arguments are passed. Also assert `run_autonomous_research_sync` is not called for codex mode.

- [x] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_demand_discovery_autonomous_research_runner.DemandDiscoveryAutonomousResearchRunnerTests.test_cli_codex_mode_routes_to_independent_workflow -v`

- [x] **Step 3: Add CLI dispatch**

Add `codex` to `--mode`, then branch before the existing fake/real call. The branch calls `run_codex_workflow_sync` and returns. Do not modify `run_autonomous_research_sync` or the Phase 5 implementation.

- [x] **Step 4: Run test to verify it passes**

Run the same targeted unittest command.

### Task 3: Verification

**Files:**
- Modify only if targeted tests expose integration issues.

- [x] **Step 1: Run focused tests**

Run:

```powershell
python -m unittest tests.test_demand_discovery_codex_workflow tests.test_demand_discovery_autonomous_research_runner -v
```

- [x] **Step 2: Run syntax verification**

Run:

```powershell
python -m py_compile src\knowledgegraph\demand_discovery\codex_workflow.py scripts\demand_discovery_autonomous_research.py
```

- [x] **Step 3: Optional real Codex smoke**

If `codex` is configured, run:

```powershell
python scripts\demand_discovery_autonomous_research.py --mode codex --topic "低空无人机探测预警能力缺口" --run-id codex-workflow-smoke --max-rounds 1
```

Expected artifacts: `outputs/runs/codex-workflow-smoke/round_summary.json`, `domain.jsonl`, `trace.jsonl`, and `report.md`.

## Self-Review

- Existing Phase 5 main chain remains untouched.
- The new runner can reuse durable domain modules but owns its control flow.
- CLI change is dispatch-only.
- Codex native search is handled inside the independent runner, not by changing shared runtime helpers.

## Completion Evidence

- Focused unit tests passed: `python -m unittest tests.test_demand_discovery_codex_workflow tests.test_demand_discovery_autonomous_research_runner -v`.
- Syntax verification passed: `python -m py_compile src\knowledgegraph\demand_discovery\codex_workflow.py scripts\demand_discovery_autonomous_research.py`.
- Real Codex smoke produced `outputs/runs/codex-workflow-smoke/round_summary.json`, `domain.jsonl`, `trace.jsonl`, `report.md`, and `report_manifest.json`.
- Smoke summary records `execution = independent_codex_workflow`, 6 role outputs, 4 accepted whitelist sources, and 7 accepted whitelist evidence cards.

## Quality Pass Completion Evidence

- Codex role prompts now reuse main-chain `reader.md`, `judge.md`, `auditor.md`, and `reporter.md`; Codex-only `planner.md` and `synthesizer.md` live under `src/knowledgegraph/demand_discovery/workers/codex_roles/`.
- Independent Codex workflow now runs `planner -> (reader workers -> judge -> next_round_plan worker_briefs)* -> synthesizer -> auditor -> reporter`.
- Judge-produced `controller_tasks` and `worker_briefs` are repaired/validated with the existing `judgement_plan` and `judge_plan_routing` helpers before dispatching the next reader round.
- Reporter output now passes through a local report-quality gate and can be rewritten with `report_quality_feedback` before publication.
- Added focused tests for prompt reuse, judge-worker follow-up routing, and thin-report rewrite.

## Reader Evidence Materialization Completion Evidence

- Reader accepted evidence is now materialized after import and before judge: the workflow can use existing `fetch_page` / `download_document`, `classify_source_page`, `read_document`, and `ArtifactStore` helpers to save raw/simplified source artifacts.
- `source_materials` are carried into worker reports, judge, synthesizer, auditor, reporter payloads, and `round_summary.json`.
- When a materialized paragraph can be matched, the workflow rewrites `EvidenceCard.source_location` and `EvidenceCard.excerpt` to the local artifact paragraph reference before downstream roles run.
- Added focused tests for injectable materialization and default tool-backed materialization.
