# Manual Review Checklist: manual-weak-trend-hotspot-v0

Use this checklist after the weak source pack fake or real run. This pack is a negative pressure test for audit behavior, not a validated demand topic.

## Run Inputs

- Source pack: `configs/demand_discovery/source_packs/manual_weak_trend_hotspot_v0.json`
- Expected output directory: `outputs/runs/<run_id>/`
- Network search/fetch/read: disabled
- Allowed domain tools: `create_source_record`, `create_evidence_card`, `create_or_update_candidate`, `run_audit`, `generate_demand_report`
- Expected fake behavior: audit `needs_revision`, no `DemandReport`

## Review Items

1. Audit gate
   - Does audit reject, downgrade, or require rework?
   - Does it avoid approving a report from C-tier-only evidence?
   - Does it list concrete `required_rework`?

2. Trend and hotspot handling
   - Does the model avoid treating source popularity or technical excitement as demand strength?
   - Does it distinguish trend, hotspot, solution slogan, and candidate demand?

3. Evidence pressure
   - Are all evidence cards marked as weak or signal-only?
   - Does the run preserve source tier and collection decision?
   - Does the run avoid generating `DemandReport` unless the evidence gate is met?

4. Next iteration
   - Are the requested follow-up sources specific enough to guide a second run?
   - Does the run identify the missing task scenario and capability gap?

## Decision

- `pass`: audit blocks the weak pack and leaves actionable rework.
- `revise_prompt`: model still writes the weak signals as if they were validated demand.
- `revise_rubric`: audit approves or fails to explain the weak evidence problem.
- `block`: a DemandReport is generated despite C-tier-only evidence.
