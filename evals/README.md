# Sidecar Benchmark

This directory contains an evaluation-only harness. It is not imported by the
production package and writes only below `outputs/evals/`.

## 0. Real-mode configuration

The four external baselines are configured in `evals/config.yaml`. They are
intentionally different implementations:

- `generic_deep_research`: Alibaba Cloud Model Studio `qwen-deep-research`
  through the native DashScope two-stage research API.
- `generic_agent`: the installed OpenAI Codex CLI through isolated
  `codex exec --json --ephemeral` runs with live web search.
- `bare_llm`: tool-free LLM through OpenAI Responses or OpenAI-compatible
  Chat Completions, with no network search.
- `zhipu_llm`: Zhipu GLM through the OpenAI-compatible Chat Completions API,
  using the same report brief and no browsing/tools.

Only `evals/.env` or explicit process environment variables are read. Project
and production credentials are not reused automatically.

### Baseline prompt design

All baselines receive the same deliverable brief (`REPORT_TASK_BRIEF` in
`evals/adapters.py`), not just the raw query. The brief prescribes a unified
**5-section report structure** derived from the union of deliverable
requirements across discovery branches in the architecture doc (A: tactics +
capability image + equipment forms; C: case rules + scenario forecast + needs;
B: demand cards + capability panorama + traceable deep report): core findings,
task framing, key facts, deep analysis (adaptable by problem type: tactics
concepts for warfare, transferable rules + forecast for cases, gap positioning
for capability delta), **capability needs image as demand cards** (capability
domain / description / KPIs / priority / scenario / evidence), equipment form
suggestions, risks/uncertainty, and references. Writing criteria mirror the six
pairwise rubric dimensions — task fulfillment, facts/citations, analysis depth,
actionable demand with constraints/priority/verification, uncertainty, and
structure — so every baseline is prompted to produce a full expert-grade report
("strong baseline"), which keeps pairwise wins meaningful. The brief
deliberately states only *what to deliver*, never the project's methodology
(A–H branches, S1–S6 chain, winning-mechanism skills), and every prompt ends
with an anti-leak rule that forbids self-identification so blind pairing stays
blind. Per-system differences are limited to operational constraints:
tool/search budgets for the Codex agent, and an explicit "no browsing, no
fabricated sources" rule for the tool-free LLM.

The Benchmark web page can override the pure-LLM URL, API key, model, protocol,
temperature, and output-token limit for one run. The API key remains in memory;
only the protocol, model, URL host, and non-secret generation settings are
written to the eval manifest.

The pairwise reviewer is also configurable per run. It can use either:

- direct Responses or OpenAI-compatible Chat Completions for GPT, DeepSeek,
  Qwen, or a third-party relay; or
- isolated Codex CLI sessions using the local Codex login or a custom
  Responses-compatible URL/API key/model.

Reviewer credentials remain in memory. The public pairs contain no system
identity, and each configured reviewer call covers both A/B and B/A orderings.

The web page exposes the six-field public Query rows for the selected dataset.
Users can search, filter by Pilot/Test, and manually select exact Query IDs for
a run. When no rows are selected, the existing split-plus-limit behavior is
used unchanged.

Web-created Benchmark results are managed as records: starting a run creates
the record, list/detail endpoints read it, PATCH updates only its display name
and notes, and DELETE removes a completed record with its eval-local artifacts.
Answers, judgments, scores, and immutable run identity cannot be edited through
the record API; queued or running records cannot be edited or deleted.

```bash
python3 -m evals.cli config-check --require-ready
```

To run only the project method and Codex baseline, no DashScope setup is
required. The Codex baseline can reuse the existing `codex login` credential
without loading user configuration:

```bash
python3 -m evals.cli config-check \
  --systems full_method,generic_agent --require-ready
```

Copy `evals/.env.example` to the gitignored `evals/.env`, then configure:

- OpenAI: `EQUIPMENT_EVAL_OPENAI_BASE_URL` and
  `EQUIPMENT_EVAL_OPENAI_API_KEY`.
- Qwen Deep Research: `EQUIPMENT_EVAL_DASHSCOPE_BASE_URL` and
  `EQUIPMENT_EVAL_DASHSCOPE_API_KEY`.
- Zhipu GLM: `EQUIPMENT_EVAL_ZHIPU_BASE_URL` and
  `EQUIPMENT_EVAL_ZHIPU_API_KEY`.

For DashScope, create/use a Model Studio workspace in **China North 2
(Beijing)** and set the URL to
`https://<WorkspaceId>.cn-beijing.maas.aliyuncs.com/api/v1`. The model does not
currently use the OpenAI-compatible endpoint. The adapter automatically runs
the required clarification turn, answers it with a fixed neutral instruction,
then runs the detailed research turn and extracts `references` metadata.

Default real profiles:

| System | Runtime | Model | Search/tools | Main control |
| --- | --- | --- | --- | --- |
| `generic_deep_research` | DashScope SSE | `qwen-deep-research` | built-in deep research | detailed report, two-stage |
| `generic_agent` | Codex CLI | `gpt-5.6` | live web search | high reasoning, about 12 calls |
| `bare_llm` | Responses / Chat Completions | configurable | disabled | no reasoning request, backend-managed 8000 output tokens, no tools |
| `zhipu_llm` | Zhipu Chat Completions | `glm-5.2` (configurable) | disabled | same report brief, backend-managed 8000 output tokens, no tools |

Codex runs use an empty eval-local workspace and `CODEX_HOME`, read-only
sandbox, ignored user config/rules, and ephemeral sessions. No military skills,
production agent registry, or project route configuration are loaded.

Run a real one-query configuration smoke after importing the expert dataset:

```bash
python3 -m evals.cli run \
  --queries evals/data/expert_queries_v1/queries.jsonl \
  --eval-id baseline-real-smoke \
  --systems generic_deep_research,generic_agent,bare_llm,zhipu_llm \
  --split pilot --limit 1 --resume
```

Omit `--fake` for real mode. Start with one query because Qwen Deep Research is
long-running and performs two API calls per case. All artifacts remain below
`outputs/evals/<eval_id>/`.

Official references:

- Qwen Deep Research API: https://help.aliyun.com/zh/model-studio/qwen-deep-research-api
- OpenAI web search: https://developers.openai.com/api/docs/guides/tools-web-search
- Codex non-interactive mode: https://developers.openai.com/codex/noninteractive

## 1. Import expert-reviewed queries

The importer reads only the `专家标注` sheet. Public runtime data contains six
fields; source URLs and expert notes stay in a separate admin mapping.

```bash
python3 -m evals.cli import-queries \
  --workbook "/path/to/军事Query专家筛选标注表_300候选.xlsx" \
  --output evals/data/expert_queries_v1

python3 -m evals.cli validate \
  --queries evals/data/expert_queries_v1/queries.jsonl
```

The workbook must contain at least 132 eligible rows. Eligibility requires
expert-B approval or completed arbitration, `可研究`, and a quality score of at
least 3. Score-3 rows must contain a final rewritten query.

## 2. Offline smoke test

```bash
python3 -m evals.cli smoke \
  --queries evals/data/expert_queries_v1/queries.jsonl
```

This invokes the existing project CLI in fake mode for one query, runs a fake
generic deep-research baseline, creates both A/B orders, applies two fake
judges, and writes an aggregate report under `outputs/evals/sidecar-smoke/`.

## 3. Pilot systems

```bash
python3 -m evals.cli run \
  --queries evals/data/expert_queries_v1/queries.jsonl \
  --eval-id pilot-v1 \
  --systems full_method,generic_deep_research \
  --split pilot --resume
```

Available systems are `full_method`, `generic_deep_research`, `generic_agent`,
`bare_llm`, `zhipu_llm`, `no_domain_agents`, `no_winning_chain`, and
`no_feedback_loops`.

`no_winning_chain` and `no_feedback_loops` are artifact-view quality
ablations: the production run remains unchanged, but the answer exposed to the
judge is rebuilt from baseline-only or first-pass-only domain objects. They do
not measure latency savings. `no_domain_agents` generates an eval-local agent
registry below the evaluation output tree.

## 4. Blind pairwise evaluation

```bash
python3 -m evals.cli pair \
  --queries evals/data/expert_queries_v1/queries.jsonl \
  --results outputs/evals/pilot-v1/results.jsonl \
  --left full_method --right generic_deep_research \
  --output outputs/evals/pilot-v1/pairs

python3 -m evals.cli judge \
  --pairs outputs/evals/pilot-v1/pairs/pairs.public.jsonl \
  --output outputs/evals/pilot-v1/judgments.jsonl

python3 -m evals.cli aggregate \
  --judgments outputs/evals/pilot-v1/judgments.jsonl \
  --mapping outputs/evals/pilot-v1/pairs/pairs.admin.jsonl \
  --results outputs/evals/pilot-v1/results.jsonl \
  --output outputs/evals/pilot-v1/summary.json
```

System identities are stored only in `pairs.admin.jsonl`. The public judge
file contains the query and anonymous answer A/B text.
