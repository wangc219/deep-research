# Manual Review Checklist: manual-cuas-low-altitude-v0

Use this checklist after the first manual source pack real run. This file is for human review of the run output, not an automated pass/fail script.

## Run Inputs

- Source pack: `configs/demand_discovery/source_packs/manual_cuas_low_altitude_v0.json`
- Expected output directory: `outputs/runs/<run_id>/`
- Network search/fetch/read: disabled
- Allowed domain tools: `create_source_record`, `create_evidence_card`, `create_or_update_candidate`, `run_audit`, `generate_demand_report`

## Minimum Output Files

- `run_config.json`
- `domain.jsonl`
- `trace.jsonl`
- `report.md`
- `manual_review_checklist.md`

## Review Items

1. Trace lineage
   - Can the run reconstruct `source -> evidence -> candidate -> audit -> report`?
   - Does every report evidence id appear in the candidate evidence ids?
   - Does the report cite the approved audit id?

2. Source audit
   - Does every `SourceRecord` include `source_name`, `source_tier`, `source_type`, `url_or_path`, `summary_text`, `summary_source`, and `collection_decision`?
   - Are C/D sources absent from the report gate evidence?
   - Are summaries clearly model/manual pack summaries rather than source facts?

3. Evidence quality
   - Is each `EvidenceCard.claim` an atomic claim?
   - Does each evidence item have a short excerpt or paraphrase and a source location?
   - Are limitations captured in `evidence_assessment`?

4. Candidate demand quality
   - Does `demand_statement` describe a need, gap, constraint, or new capability space?
   - Does it avoid becoming a fixed weapon/equipment/technical solution?
   - Does it distinguish threat, task setting, existing capability state, gap, and uncertainty?

5. Audit behavior
   - Does the audit explain why the candidate is approved, needs revision, downgraded, or rejected?
   - If approved, does it cite at least one non-C/D evidence item with an excerpt?
   - If weak, does it prevent report generation and leave `required_rework`?

6. Report quality
   - Does the report read like a demand-analysis investigation report?
   - Does it separate public-source fact, model inference, uncertainty, and solution clues?
   - Does it include open questions and next validation needs?

## First-Run Decision

- `pass`: pipeline and report are usable for the next source pack.
- `revise_prompt`: evidence/candidate/report exists but model wording is weak.
- `revise_rubric`: audit is too permissive or too strict.
- `revise_template`: report structure is hard to review.
- `block`: trace, gate, or domain writes are incorrect.

