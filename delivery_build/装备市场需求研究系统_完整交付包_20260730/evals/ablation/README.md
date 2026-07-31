# Ablation extension

This optional extension implements the three-arm ablation experiment:

- `full_method`
- `no_multisource_baseline`
- `no_winning_mechanism`

Enable or disable the backend router with:

```dotenv
EQUIPMENT_DR_ENABLE_ABLATION=1
```

When disabled, the Web workbench probes `/api/v1/ablations/overview` and hides
the navigation entry. To remove the extension completely, delete this directory
and `apps/web/src/features/ablation/`; the backend uses an optional import and
the frontend uses `import.meta.glob`, so the core project continues to build.

Artifacts are written only below `outputs/evals/ablations/<experiment_id>/`.
