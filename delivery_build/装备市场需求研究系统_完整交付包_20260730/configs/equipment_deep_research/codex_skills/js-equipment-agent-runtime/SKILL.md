---
name: js-equipment-agent-runtime
description: Execute one bounded JS equipment-market research role as a Codex CLI agent. Use when the prompt contains agent_runtime with active business skills, governed tools, a Harness profile, A-H discovery branches, S1-S6 winning-mechanism steps, or inner/middle/outer/meta loop controls.
---

# Execute the assigned agent role

Treat `agent_runtime` as the authoritative role contract for this isolated Codex CLI turn.

1. Read the role, phase, active skills, governed tools, output contract, evidence policy, Harness budget, quality gates, stopping conditions, and recovery policy before analyzing the task.
   - If `agent_runtime.agent_id` is `orchestrator`, read `references/orchestrator.md` completely before making any planning decision.
   - If `agent_runtime.agent_id` is `international_situation`, read `references/international_situation.md` completely before searching or forming background hypotheses.
   - If `agent_runtime.agent_id` is `combat_scenario`, read `references/combat_scenario.md` completely before constructing or scoring scenarios.
   - If `agent_runtime.agent_id` is `weapon_equipment`, read `references/weapon_equipment.md` completely before searching, comparing variants, or forming equipment requirements.
   - During `web_discovery`, use `task_input.source_priorities` as the first-pass source queue. If it is absent or insufficient, read the matching agent section in `references/source-priorities.json`. Revalidate every page and continue open search for freshness, independent corroboration, counterevidence, and missing source families.
   - Treat `retrieval_lane=known_sources` as the fast lane for previously successful official pages and `retrieval_lane=open_web` as the novelty/counterevidence lane. Keep their findings distinguishable until URL deduplication.
   - If `task_input.incremental_knowledge` is present, read `references/business-agent-memory.md` completely. Use memory only to identify deltas, aliases, likely primary sites and unresolved questions; never cite memory as current evidence.
   - If the system prompt also invokes `$js-winning-shared-layer`, use it for Tree-of-Warfare nodes, dynamic specialist governance, and knowledge-pack access; the current role contract remains authoritative.
2. Apply only the active skills supplied for this role. Follow each skill's steps in order and produce its required artifacts or the requested typed JSON projection.
3. Treat `agent_runtime.knowledge_packs` as the allowed knowledge projection boundary, not as evidence. Claims still require an input EvidenceCard or must be labeled as inference/assumption.
4. Treat governed tool names as local Harness operations. Plan and structure inputs according to their semantics, but never claim that Codex executed a Harness tool directly. The parent Harness validates permissions, records traces, materializes evidence, and commits objects.
5. Separate sourced facts, reasoned inferences, assumptions, conflicts, counterevidence, and open questions. Cite only inspected public HTTPS sources when web research is enabled.
6. Stop when the Harness stop conditions are satisfied. If a budget or loop limit is reached, return the best bounded result with explicit limitations instead of silently continuing.
7. On critique failure, identify the earliest invalid node and return targeted retry guidance. Do not restart unaffected work.
8. Treat prior source recommendations as navigation memory, never as factual memory. A previously accepted URL must still be inspected, materialized, dated, and assessed in the current run.
9. During `evidence_analysis_repair`, return only missing fields. Preserve valid fields and discovered-source boundaries; do not repeat the full research workflow.
10. Stop discovery when the Harness reports evidence sufficiency: the minimum accepted evidence, independent source domains, counterevidence/limitations, materialization and role-specific structural gates are all satisfied. A raw URL count alone is not a completion criterion.

## Pipeline discipline

- Allow discovery to start before upstream analysis packets are complete.
- Wait for upstream typed packets only before the dependent analysis synthesis.
- Consume only the target-specific projection supplied in `upstream_handoffs`; request a focused recall instead of demanding another Agent's full packet or raw session.
- Keep final business analysis at the configured high reasoning level. Use reduced reasoning only for source navigation, formatting, deduplication and missing-field repair.

## Loop discipline

- Inner loop: critique the current S-step; retry only that step when evidence, logic, schema, or safety checks fail.
- Middle loop: after S1-S6, verify causal continuity and rerun from the earliest broken step.
- Outer loops L1-L3: request focused evidence or feasibility repair at the declared return node; preserve accepted upstream artifacts.
- Meta loop L4: reconsider the A-H path or Agent set only when repeated repair fails, coverage materially changes, or a major contradiction invalidates the blueprint.

## Output discipline

Return only the requested final content. When an output schema is supplied, emit strict JSON with no Markdown fence. Do not add unsupported numbers, sources, capabilities, or tool-execution claims.
