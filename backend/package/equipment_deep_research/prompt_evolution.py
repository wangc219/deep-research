"""Governed self evolution of the dynamic winning prompts.

The Codex agent proposes complete prompt files; it never writes them directly.
An explicit review records the decision, while a tenant-scoped proposal is
promoted to the deployment-wide live prompt directory only by a platform
administrator that opts into cross-scope publication.  Every proposal is kept
as an auditable, reversible record.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from threading import RLock
from typing import Any, Mapping, Sequence
from uuid import uuid4

from equipment_deep_research.agents.dynamic_prompt_resources import (
    invalidate_dynamic_winning_prompt_cache,
    load_dynamic_winning_prompt,
)
from equipment_deep_research.config.settings import load_settings
from equipment_deep_research.providers.base import ModelMessage

STAGES = tuple(f"S{i}" for i in range(1, 7))
PROMPT_KEYS = ("common", *STAGES)
PROMPT_EFFECT_STATUSES = (
    "validated",
    "effective",
    "ineffective",
    "inconclusive",
    "superseded",
    "withdrawn",
)
# These statuses are tombstones for a Prompt candidate.  They intentionally
# cannot transition back to ``validated``/``effective``: doing so would let a
# delayed evaluator callback resurrect a superseded or withdrawn candidate.
_IMMUTABLE_PROMPT_EFFECT_STATUSES = frozenset({"superseded", "withdrawn"})
_lock = RLock()


# ``evals.replay`` is intentionally kept as an offline sidecar and is not
# imported by the production package.  Keep the small wire-contract validator
# here instead: the API must not accept a hand-written ``gate.passed`` bit as
# promotion evidence.  These are the arms understood by the replay sidecar;
# ``neither`` is optional but useful for four-arm attribution.
_REPLAY_ARMS = frozenset({"prompt_only", "memory_only", "both", "neither"})
_REPLAY_REQUIRED_ARMS = frozenset({"prompt_only", "memory_only", "both"})
_SHA256_RE = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$", re.IGNORECASE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path(root: Path) -> Path:
    return Path(root).resolve().parent / "knowledge" / "prompt-evolution.json"


def _project_root() -> Path:
    """Resolve the repository root without embedding a developer path."""

    return load_settings().paths.root


def _relative_project_path(path: Path) -> str:
    """Persist relocatable project paths in the evolution ledger."""

    try:
        return path.resolve().relative_to(_project_root()).as_posix()
    except ValueError:
        # A custom deployment may place prompt snapshots outside the source
        # tree.  Keep the ledger portable by storing a descriptive filename;
        # the runtime can still use the in-process path for the current turn.
        return path.name


def _text_hash(value: Any) -> str:
    return "sha256:" + sha256(str(value or "").encode("utf-8")).hexdigest()


def _require_effect_evidence(
    evaluator_id: Any,
    evaluation_id: Any,
) -> tuple[str, str]:
    """Require explicit, auditable actors for effect-status transitions."""

    evaluator = str(evaluator_id or "").strip()[:160]
    evaluation = str(evaluation_id or "").strip()[:160]
    if not evaluator:
        raise ValueError("evaluator_id is required for effect status updates")
    if not evaluation:
        raise ValueError("evaluation_id is required for effect status updates")
    return evaluator, evaluation


def _guard_effect_transition(
    prior_status: Any,
    next_status: str,
    *,
    prior_evaluator_id: Any = "",
    prior_evaluation_id: Any = "",
    next_evaluator_id: str = "",
    next_evaluation_id: str = "",
) -> bool:
    """Reject resurrection from Prompt effect tombstones.

    ``True`` denotes an exact same-state/evidence retry, which callers may
    safely treat as idempotent.  A changed status or evidence reference is a
    conflict and must be represented by a new proposal/evaluation cycle.
    """

    prior = str(prior_status or "pending_validation").strip().lower()
    if prior not in _IMMUTABLE_PROMPT_EFFECT_STATUSES:
        return False
    if prior != next_status:
        raise ValueError(
            f"cannot transition immutable prompt effect status: {prior} -> {next_status}"
        )
    previous_evaluation = str(prior_evaluation_id or "").strip()[:160]
    if previous_evaluation and previous_evaluation != next_evaluation_id:
        raise ValueError("immutable prompt effect status has different evidence")
    previous_evaluator = str(prior_evaluator_id or "").strip()[:160]
    if previous_evaluator and previous_evaluator != next_evaluator_id:
        raise ValueError("immutable prompt effect status has different evaluator")
    return True


def _bounded_strings(value: Any, *, limit: int) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, (list, tuple, set)) else [value]
    result: list[str] = []
    for item in values:
        if item is None:
            continue
        text = str(item).strip()
        if text:
            result.append(text[:240])
    return result[:limit]


def _versions_root() -> Path:
    return Path(__file__).resolve().parent / "agents" / "prompts" / "dynamic_winning" / "versions"


def _section_manifest_path() -> Path:
    return Path(__file__).resolve().parent / "agents" / "prompts" / "dynamic_winning" / "section_manifest.json"


_PROMPT_SECTION_RE = re.compile(
    r"^<!-- prompt: ([\w.]+) -->\n(.*?)\n<!-- /prompt -->$",
    re.MULTILINE | re.DOTALL,
)


def _prompt_root() -> Path:
    return Path(__file__).resolve().parent / "agents" / "prompts" / "dynamic_winning"


def _prompt_key(value: Any) -> str:
    key = str(value or "").strip()
    if key.upper() == "COMMON":
        key = "common"
    elif key.upper() in STAGES:
        key = key.upper()
    if key not in PROMPT_KEYS:
        raise ValueError(f"prompt stage must be one of {PROMPT_KEYS}")
    return key


def _read_prompt_sections(stage: Any) -> tuple[str, dict[str, str], str]:
    key = _prompt_key(stage)
    path = _prompt_root() / f"{key}.md"
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"prompt file is unreadable: {key}") from exc
    sections = {name: body for name, body in _PROMPT_SECTION_RE.findall(source)}
    # S6's five independently authored portrait-column briefs are stored in
    # companion Markdown files. Keep the returned source rooted at S6.md so
    # governed system-section patches still publish only that file, while
    # exposing the companion sections to proposal/evolution readers.
    if key == "S6":
        for companion in sorted(_prompt_root().glob("S6_[0-9].md")):
            try:
                companion_source = companion.read_text(encoding="utf-8")
            except OSError as exc:
                raise ValueError(f"prompt file is unreadable: {companion.name}") from exc
            companion_sections = _PROMPT_SECTION_RE.findall(companion_source)
            if not companion_sections:
                raise ValueError(f"prompt file has no reviewable sections: {companion.name}")
            for name, body in companion_sections:
                if name in sections:
                    raise ValueError(f"duplicate dynamic prompt section: {key}/{name}")
                sections[name] = body
    if not sections:
        raise ValueError(f"prompt file has no reviewable sections: {key}")
    return key, sections, source


def _section_hash(value: Any) -> str:
    return _text_hash(value)


def _manifest_payload(manifest_path: Path | None = None) -> dict[str, Any]:
    path = manifest_path or _section_manifest_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError(f"section manifest unreadable: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("section manifest must be an object")
    return dict(payload)


def _pattern_matches(pattern: Any, section_id: str) -> bool:
    pattern_text = str(pattern or "").strip()
    if not pattern_text:
        return False
    if pattern_text.endswith(".*"):
        return section_id.startswith(pattern_text[:-1])
    return section_id == pattern_text


def _section_policy(stage: str, section_id: str) -> tuple[bool, bool]:
    manifest = _manifest_payload()
    files = manifest.get("files", {})
    spec = files.get(stage, {}) if isinstance(files, Mapping) else {}
    if not isinstance(spec, Mapping):
        return False, False
    mutable = any(_pattern_matches(pattern, section_id) for pattern in spec.get("mutable_sections", []))
    protected = any(_pattern_matches(pattern, section_id) for pattern in spec.get("protected_sections", []))
    # A whole ``system`` replacement would implicitly replace protected
    # sub-sections such as output_schema/evidence_boundary/identity_freeze.
    # Require challengers to patch a leaf section instead of bypassing those
    # immutable contracts through a broad parent marker.
    if section_id == "system" and any(
        str(pattern).strip().startswith("system.")
        for pattern in spec.get("protected_sections", [])
    ):
        protected = True
    return mutable, protected


def _active_prompt_bundle_hash() -> str:
    """Hash only the active dynamic-winner resources, excluding snapshots."""

    root = _prompt_root()
    files: dict[str, str] = {}
    if root.is_dir():
        for path in sorted(root.rglob("*")):
            if not path.is_file() or "versions" in path.relative_to(root).parts:
                continue
            if path.name == ".DS_Store" or path.suffix.lower() not in {".md", ".json"}:
                continue
            files[path.relative_to(root).as_posix()] = sha256(path.read_bytes()).hexdigest()
    return "sha256:" + sha256(
        json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _validate_patch_text(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) < 20:
        raise ValueError("section patch is too short")
    if "<!-- prompt:" in text or "```" in text:
        raise ValueError("section patch must contain prose/JSON content only")
    return text


def _normalise_patch_section(value: Any) -> tuple[str, str]:
    """Return ``(stage, section_id)`` for a patch identifier.

    The public contract uses ``S4:section.name``.  A dot-only form is accepted
    for older challenger generators, but only when the prefix is an actual
    stage name; section names themselves may contain dots.
    """

    raw = str(value or "").strip()
    if ":" in raw:
        stage, section = raw.split(":", 1)
    elif "." in raw:
        prefix, section = raw.split(".", 1)
        stage = prefix if prefix.upper() in STAGES or prefix.lower() == "common" else ""
        if not stage:
            raise ValueError("section_id must use STAGE:section form")
    else:
        raise ValueError("section_id must use STAGE:section form")
    stage_key = _prompt_key(stage)
    section_id = str(section or "").strip()
    if not section_id or any(char in section_id for char in "\r\n"):
        raise ValueError("section_id is required")
    return stage_key, section_id


def _replace_prompt_section(source: str, section_id: str, new_text: str) -> str:
    marker = re.compile(
        rf"(^<!-- prompt: {re.escape(section_id)} -->\n)(.*?)(\n<!-- /prompt -->$)",
        re.MULTILINE | re.DOTALL,
    )
    match = marker.search(source)
    if match is None:
        raise ValueError(f"prompt section is missing: {section_id}")
    return source[: match.start()] + match.group(1) + new_text + match.group(3) + source[match.end() :]


def _candidate_from_section_patches(
    *,
    selected: Sequence[str],
    section_patches: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, str], list[dict[str, Any]], dict[str, str]]:
    """Validate and materialise section patches without touching production.

    The returned ``after`` values are the complete ``system`` sections used by
    the legacy ledger/publisher, while each patch also retains its exact
    section-level hash and metadata.  This lets older readers continue to
    inspect proposals while newer reviewers can enforce mutable/protected
    boundaries and compare-and-swap hashes.
    """

    if not section_patches:
        raise ValueError("section_patches must not be empty")
    selected_set = set(selected)
    sources: dict[str, str] = {}
    sections: dict[str, dict[str, str]] = {}
    for stage in selected:
        key, parsed, source = _read_prompt_sections(stage)
        sources[key] = source
        sections[key] = parsed
    materialized: list[dict[str, Any]] = []
    touched: set[str] = set()
    for raw_patch in section_patches:
        if not isinstance(raw_patch, Mapping):
            raise ValueError("each section patch must be an object")
        stage, section_id = _normalise_patch_section(
            raw_patch.get("section_id") or raw_patch.get("id")
        )
        if stage not in selected_set:
            raise ValueError(f"section patch stage is not selected: {stage}")
        mutable, protected = _section_policy(stage, section_id)
        if protected or not mutable:
            raise ValueError(f"section is not mutable: {stage}:{section_id}")
        if section_id not in sections[stage]:
            raise ValueError(f"prompt section is missing: {stage}:{section_id}")
        if f"{stage}:{section_id}" in touched:
            raise ValueError(f"duplicate section patch: {stage}:{section_id}")
        touched.add(f"{stage}:{section_id}")
        old_text = sections[stage][section_id]
        old_hash = _section_hash(old_text)
        declared_old_hash = str(raw_patch.get("old_hash", "")).strip()
        if declared_old_hash and declared_old_hash != old_hash:
            raise ValueError(f"section compare-and-swap mismatch: {stage}:{section_id}")
        new_text = _validate_patch_text(
            raw_patch.get("new_text")
            or raw_patch.get("new_content")
            or raw_patch.get("replacement")
        )
        sections[stage][section_id] = new_text
        sources[stage] = _replace_prompt_section(sources[stage], section_id, new_text)
        materialized.append(
            {
                **dict(raw_patch),
                "section_id": f"{stage}:{section_id}",
                "old_hash": old_hash,
                "new_hash": _section_hash(new_text),
                "new_text": new_text,
                "legacy_full_section": False,
            }
        )
    # ``after`` is intentionally the complete system prose for compatibility;
    # non-system sections are published from ``materialized`` by the governed
    # bundle publisher below.
    after = {
        stage: sections[stage].get("system", "")
        for stage in selected
    }
    return after, materialized, sources


def validate_section_manifest(manifest_path: Path | None = None) -> dict[str, Any]:
    """Validate the static prompt dependency manifest against checked-in files.

    This is intentionally a read-only preflight.  It catches drift in paths,
    stage names, and declared sections before a proposal is reviewed; it does
    not reject legacy full-section proposals, which remain compatible but are
    reported as requiring section-level migration.
    """
    path = Path(manifest_path) if manifest_path else _section_manifest_path()
    # The manifest is returned to API/CLI callers as an audit reference.  Do
    # not leak the checkout's absolute path into a persisted response: the
    # same ledger must remain readable after the project is moved to another
    # host or mounted under a different prefix.
    portable_manifest_path = _relative_project_path(path)
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        return {
            "ok": False,
            "manifest_path": portable_manifest_path,
            "errors": [f"manifest unreadable: {exc}"],
        }
    errors: list[str] = []
    root = path.parent
    files = manifest.get("files", {})
    if not isinstance(files, Mapping):
        errors.append("files must be an object")
        files = {}
    for stage, spec in files.items():
        if stage not in {"common", *STAGES}:
            errors.append(f"unknown stage: {stage}")
            continue
        if not isinstance(spec, Mapping) or not str(spec.get("path", "")):
            errors.append(f"{stage}: path is required")
            continue
        rel = Path(str(spec["path"]))
        if rel.is_absolute() or ".." in rel.parts:
            errors.append(f"{stage}: path must be project-relative and contained")
            continue
        target = root / rel
        if not target.is_file():
            errors.append(f"{stage}: prompt file is missing: {rel}")
            continue
        companion_paths = spec.get("companion_paths", [])
        if companion_paths is None:
            companion_paths = []
        if not isinstance(companion_paths, (list, tuple)):
            errors.append(f"{stage}: companion_paths must be an array")
            companion_paths = []
        for raw_companion in companion_paths:
            companion_rel = Path(str(raw_companion))
            if companion_rel.is_absolute() or ".." in companion_rel.parts:
                errors.append(f"{stage}: companion path must be project-relative and contained: {companion_rel}")
                continue
            companion_target = root / companion_rel
            if not companion_target.is_file():
                errors.append(f"{stage}: companion prompt file is missing: {companion_rel}")
                continue
            companion_source = companion_target.read_text(encoding="utf-8")
            if not _PROMPT_SECTION_RE.search(companion_source):
                errors.append(f"{stage}: companion prompt has no reviewable section: {companion_rel}")
        headings = {line[3:].strip() for line in target.read_text(encoding="utf-8").splitlines() if line.startswith("## ")}
        for section in [*spec.get("mutable_sections", []), *spec.get("protected_sections", [])]:
            section = str(section)
            if "*" not in section and section not in headings and not section.startswith("system."):
                errors.append(f"{stage}: declared section is missing: {section}")
    return {
        "ok": not errors,
        "manifest_path": portable_manifest_path,
        "errors": errors,
        "schema_version": manifest.get("schema_version", ""),
    }


def _version_rows(root: Path) -> list[dict[str, Any]]:
    return [x for x in _read(root) if x.get("record_type") == "version"]


def _read(root: Path) -> list[dict[str, Any]]:
    path = _path(root)
    try:
        value = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
    except (OSError, ValueError, TypeError):
        value = []
    return [dict(x) for x in value if isinstance(x, Mapping)] if isinstance(value, list) else []


def _write(root: Path, rows: list[dict[str, Any]]) -> None:
    path = _path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    tmp.write_text(json.dumps(rows[-500:], ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _render_system_replacement(source: str, prompt: str) -> str:
    marker, end = "<!-- prompt: system -->", "<!-- /prompt -->"
    try:
        start = source.index(marker) + len(marker)
        finish = source.index(end, start)
    except ValueError as exc:
        raise ValueError("prompt system section markers are missing") from exc
    return source[:start] + "\n" + prompt + "\n" + source[finish:]


def _next_version(rows: Sequence[Mapping[str, Any]], stage: str) -> tuple[str, str]:
    existing = [row for row in rows if row.get("record_type") == "version" and row.get("stage") == stage]
    number = max(
        [
            int(str(row.get("version", "v0000"))[1:])
            for row in existing
            if str(row.get("version", "v0000")).startswith("v")
            and str(row.get("version", "v0000"))[1:].isdigit()
        ]
        or [0]
    ) + 1
    return f"v{number:04d}", current_version_from_rows(rows, stage)


def current_version_from_rows(rows: Sequence[Mapping[str, Any]], stage: str) -> str:
    matches = [
        row
        for row in rows
        if row.get("record_type") == "version"
        and row.get("stage") == stage
        and row.get("active")
    ]
    return str(matches[-1].get("version", "v0000")) if matches else "v0000"


def _publish_sources_atomic(
    output_root: Path,
    sources: Mapping[str, str],
    *,
    reason: str,
    source: str,
    expected_parent_bundle_hash: str = "",
    snapshot_format: str = "markdown",
    scope: Mapping[str, Any] | None = None,
    source_proposal_id: str = "",
    rollback_from: str = "",
) -> list[dict[str, Any]]:
    """Publish several prompt files as one compare-and-swap transaction.

    Files are prepared beside their live targets and swapped only after every
    target has been validated.  If a later replacement or ledger write fails,
    original bytes are restored.  Version snapshots are append-only and use
    project-relative ledger paths.
    """

    normalized_sources = {
        _prompt_key(stage): str(content)
        for stage, content in sources.items()
    }
    if not normalized_sources:
        raise ValueError("at least one prompt source is required")
    actual_hash = _active_prompt_bundle_hash()
    if expected_parent_bundle_hash and expected_parent_bundle_hash != actual_hash:
        raise ValueError("prompt bundle compare-and-swap mismatch")
    root = _prompt_root()
    targets: dict[str, Path] = {}
    originals: dict[str, bytes] = {}
    for stage, content in normalized_sources.items():
        target = root / f"{stage}.md"
        if target.is_symlink() or not target.is_file():
            raise ValueError(f"prompt target is unsafe or missing: {stage}")
        targets[stage] = target
        originals[stage] = target.read_bytes()
        if "<!-- prompt:" not in content or "<!-- /prompt -->" not in content:
            raise ValueError(f"prompt source has invalid section markers: {stage}")
    rows = _read(output_root)
    records: list[dict[str, Any]] = []
    temporary: dict[str, Path] = {}
    snapshots: list[Path] = []
    try:
        for stage, content in normalized_sources.items():
            version, prior = _next_version(rows, stage)
            version_dir = _versions_root() / stage
            version_dir.mkdir(parents=True, exist_ok=True)
            version_file = version_dir / f"{version}.md"
            version_file.write_text(content, encoding="utf-8")
            snapshots.append(version_file)
            candidate_sections = {
                name: body for name, body in _PROMPT_SECTION_RE.findall(content)
            }
            records.append(
                {
                    "record_type": "version",
                    "stage": stage,
                    "version": version,
                    "parent_version": prior,
                    "active": True,
                    "created_at": _now(),
                    "reason": str(reason)[:2000],
                    "source": str(source)[:240],
                    # Preserve immutable tenancy provenance on every version
                    # row.  ``source`` remains a compatibility display field;
                    # consumers must use ``source_proposal_id``/``scope`` for
                    # authorization and rollback decisions.
                    "source_proposal_id": str(source_proposal_id or "")[:200],
                    "scope": dict(scope or {}),
                    "rollback_from": str(rollback_from or "")[:32],
                    "file": _relative_project_path(version_file),
                    "file_hash": _text_hash(content),
                    "snapshot_format": snapshot_format,
                    "system_hash": _text_hash(candidate_sections.get("system", "")),
                }
            )
            temporary_path = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
            temporary_path.write_text(content, encoding="utf-8")
            temporary[stage] = temporary_path
        # Swap every prepared file.  Keep a byte-level backup in memory for a
        # best-effort rollback if an unexpected filesystem error occurs.
        for stage, target in targets.items():
            temporary[stage].replace(target)
        for row in rows:
            if row.get("record_type") == "version" and row.get("stage") in normalized_sources:
                row["active"] = False
        rows.extend(records)
        _write(output_root, rows)
    except BaseException:
        for stage, target in targets.items():
            try:
                target.write_bytes(originals[stage])
            except OSError:
                pass
        raise
    finally:
        for path in temporary.values():
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
    invalidate_dynamic_winning_prompt_cache()
    return records


def _validate(stage: str, prompt: str) -> str:
    stage = str(stage).upper().strip()
    if stage not in STAGES:
        raise ValueError(f"stage must be one of {STAGES}")
    prompt = str(prompt or "").strip()
    if len(prompt) < 120:
        raise ValueError("proposed prompt is too short")
    if "<!-- prompt: system -->" in prompt or "```" in prompt:
        raise ValueError("proposal must contain prompt prose only")
    return prompt


def create_proposal(
    *,
    output_root: Path,
    feedback: Mapping[str, Any],
    stages: Sequence[str] | None = None,
    proposed_prompts: Mapping[str, str] | None = None,
    agent: str = "codex_prompt_evolution",
    hypothesis: str = "",
    change_units: list[str] | None = None,
    target_metrics: list[str] | None = None,
    section_patches: Sequence[Mapping[str, Any]] | None = None,
    cycle_id: str = "",
    counterexamples: Sequence[str] | None = None,
    acceptance_tests: Sequence[str] | None = None,
    expected_tradeoffs: Mapping[str, Any] | None = None,
    tenant_id: str = "",
    workspace_id: str = "",
    project_id: str = "",
    profile_id: str = "",
    route: str = "",
    stage_scope: Sequence[str] | None = None,
    parent_bundle_hash: str = "",
) -> dict[str, Any]:
    patch_mode = bool(section_patches)
    if patch_mode:
        selected = list(dict.fromkeys(
            [_prompt_key(stage) for stage in (stages or [])]
            or sorted(
                {
                    _normalise_patch_section(
                        patch.get("section_id") or patch.get("id")
                    )[0]
                    for patch in section_patches or []
                    if isinstance(patch, Mapping)
                }
            )
        ))
        if not selected:
            raise ValueError("section patch proposal requires at least one stage")
        after, patches, after_sources = _candidate_from_section_patches(
            selected=selected,
            section_patches=section_patches or [],
        )
        current = {s: load_dynamic_winning_prompt(s) for s in selected}
        current_sources = {s: _read_prompt_sections(s)[2] for s in selected}
        versions = {s: current_version(output_root, s) for s in selected}
        parent_hashes = {s: _text_hash(current_sources[s]) for s in selected}
        normalized = dict(after)
        candidate_hashes = {s: _text_hash(after_sources[s]) for s in selected}
    else:
        normalized = {
            str(s).upper().strip(): _validate(str(s), p)
            for s, p in dict(proposed_prompts or {}).items()
        }
        selected = [str(s).upper().strip() for s in (stages or [])] or list(normalized)
        if not normalized or any(s not in normalized for s in selected):
            raise ValueError("proposal must include a prompt for every selected stage")
        current = {s: load_dynamic_winning_prompt(s) for s in selected}
        versions = {s: current_version(output_root, s) for s in selected}
        parent_hashes = {s: _text_hash(current[s]) for s in selected}
        candidate_hashes = {s: _text_hash(normalized[s]) for s in selected}
        patches = [
            {
                "section_id": f"{stage}:system",
                "old_hash": parent_hashes[stage],
                "new_hash": candidate_hashes[stage],
                "new_text": normalized[stage],
                "legacy_full_section": True,
            }
            for stage in selected
        ]
        after_sources = {}
    impacted_stages = list(selected)
    if any(stage in {"S3", "S4"} for stage in selected):
        impacted_stages = list(dict.fromkeys([*impacted_stages, "S3", "S4"]))
    elif "common" in selected:
        impacted_stages = list(STAGES)
    scope = {
        "tenant_id": str(tenant_id or feedback.get("tenant_id", ""))[:160],
        "workspace_id": str(workspace_id or feedback.get("workspace_id", ""))[:160],
        "project_id": str(project_id or feedback.get("project_id", ""))[:160],
        "profile_id": str(profile_id or feedback.get("profile_id", ""))[:160],
        "route": str(route or feedback.get("route", ""))[:120],
        "stage_scope": list(stage_scope or feedback.get("stage_scope", []) or []),
    }
    row = {
        "schema_version": "2.1" if patch_mode else "2.0",
        "proposal_id": f"prompt-proposal-{uuid4()}",
        "cycle_id": str(cycle_id or f"evolution-cycle-{uuid4()}"),
        "status": "pending_review",
        "publish_status": "not_published",
        "effect_status": "pending_validation",
        "evaluation_status": "not_run",
        "created_at": _now(),
        "updated_at": _now(),
        "agent": agent,
        "hypothesis": str(hypothesis or feedback.get("hypothesis", ""))[:2000],
        "change_units": _bounded_strings(
            change_units or [f"{stage}:system" for stage in selected], limit=3
        ),
        "target_metrics": _bounded_strings(
            target_metrics or feedback.get("target_metrics", []), limit=16
        ),
        "counterexamples": _bounded_strings(counterexamples, limit=8),
        "acceptance_tests": _bounded_strings(acceptance_tests, limit=12),
        "expected_tradeoffs": dict(expected_tradeoffs or {}),
        "scope": scope,
        "stages": selected,
        "feedback": dict(feedback),
        "before": current,
        "after": {s: normalized[s] for s in selected},
        "before_sources": {
            stage: _read_prompt_sections(stage)[2] for stage in selected
        },
        "after_sources": after_sources,
        "base_versions": versions,
        "parent_prompt_hashes": parent_hashes,
        "candidate_prompt_hashes": candidate_hashes,
        "section_patches": patches,
        "parent_bundle_hash": str(parent_bundle_hash or _active_prompt_bundle_hash()),
        "impacted_stages": impacted_stages,
        "static_checks": (
            {
                "schema": "pass",
                "manifest": "pass",
                "mutable_sections": "pass",
                "protected_sections": "pass",
                "compare_and_swap": "pass",
            }
            if patch_mode
            else {"schema": "not_run", "protected_sections": "not_run"}
        ),
        "replay_refs": [],
        "review_status": "pending_review",
        "canary_status": "not_started",
        "patch_only": patch_mode,
        "legacy_compatibility": not patch_mode,
    }
    with _lock:
        rows = _read(output_root)
        rows.append(row)
        _write(output_root, rows)
    return row


def create_section_patch_proposal(
    *,
    output_root: Path,
    feedback: Mapping[str, Any],
    stages: Sequence[str] | None = None,
    section_patches: Sequence[Mapping[str, Any]],
    agent: str = "codex_prompt_evolution",
    hypothesis: str = "",
    change_units: Sequence[str] | None = None,
    target_metrics: Sequence[str] | None = None,
    counterexamples: Sequence[str] | None = None,
    acceptance_tests: Sequence[str] | None = None,
    expected_tradeoffs: Mapping[str, Any] | None = None,
    tenant_id: str = "",
    workspace_id: str = "",
    project_id: str = "",
    profile_id: str = "",
    route: str = "",
    stage_scope: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Create a governed, section-level challenger without publishing it.

    This is the preferred entry point for new evolution cycles.  It performs
    mutable/protected section checks and compare-and-swap validation at
    proposal creation time, so a stale or contract-breaking candidate never
    reaches the reviewer as an apparently valid full-file replacement.
    """

    selected = [
        _prompt_key(stage)
        for stage in (stages or [])
    ]
    if not selected:
        selected = sorted(
            {
                _normalise_patch_section(patch.get("section_id") or patch.get("id"))[0]
                for patch in section_patches
                if isinstance(patch, Mapping)
            }
        )
    selected = list(dict.fromkeys(selected))
    if not selected:
        raise ValueError("section patch proposal requires at least one stage")
    after, patches, sources = _candidate_from_section_patches(
        selected=selected,
        section_patches=section_patches,
    )
    before_sources = {
        stage: _read_prompt_sections(stage)[2]
        for stage in selected
    }
    # Stage hashes cover the complete source (not only the ``system`` leaf),
    # so a replay can prove that a patch touching ``creative`` or another
    # mutable section actually exercised the intended candidate Prompt.
    parent_prompt_hashes = {
        stage: _text_hash(before_sources[stage])
        for stage in selected
    }
    candidate_prompt_hashes = {
        stage: _text_hash(sources[stage])
        for stage in selected
    }
    if any(stage in {"S3", "S4"} for stage in selected):
        # S3/S4 jointly define creative novelty and technical realization. A
        # challenger may touch one file, but its replay scope must include both
        # stages so a local gain cannot hide a downstream regression.
        impacted_stages = list(dict.fromkeys([*selected, "S3", "S4"]))
    elif "common" in selected:
        impacted_stages = list(STAGES)
    else:
        impacted_stages = list(selected)
    scope = {
        "tenant_id": str(tenant_id or feedback.get("tenant_id", ""))[:160],
        "workspace_id": str(workspace_id or feedback.get("workspace_id", ""))[:160],
        "project_id": str(project_id or feedback.get("project_id", ""))[:160],
        "profile_id": str(profile_id or feedback.get("profile_id", ""))[:160],
        "route": str(route or feedback.get("route", ""))[:120],
        "stage_scope": list(stage_scope or feedback.get("stage_scope", []) or []),
    }
    row = {
        "schema_version": "2.1",
        "proposal_id": f"prompt-proposal-{uuid4()}",
        "cycle_id": f"evolution-cycle-{uuid4()}",
        "status": "pending_review",
        "publish_status": "not_published",
        "effect_status": "pending_validation",
        "evaluation_status": "not_run",
        "created_at": _now(),
        "updated_at": _now(),
        "agent": str(agent or "codex_prompt_evolution")[:160],
        "hypothesis": str(hypothesis or feedback.get("hypothesis", ""))[:2000],
        "change_units": _bounded_strings(
            change_units or [patch["section_id"] for patch in patches], limit=3
        ),
        "target_metrics": _bounded_strings(
            target_metrics or feedback.get("target_metrics", []), limit=16
        ),
        "counterexamples": _bounded_strings(counterexamples, limit=8),
        "acceptance_tests": _bounded_strings(acceptance_tests, limit=12),
        "expected_tradeoffs": dict(expected_tradeoffs or {}),
        "scope": scope,
        "stages": selected,
        "impacted_stages": impacted_stages,
        "feedback": dict(feedback),
        "before": {stage: before_sources[stage] for stage in selected},
        "after": after,
        "after_sources": sources,
        "parent_prompt_hashes": parent_prompt_hashes,
        "candidate_prompt_hashes": candidate_prompt_hashes,
        "parent_bundle_hash": _active_prompt_bundle_hash(),
        "section_patches": patches,
        "static_checks": {
            "schema": "pass",
            "manifest": "pass",
            "mutable_sections": "pass",
            "protected_sections": "pass",
            "compare_and_swap": "pass",
        },
        "replay_refs": [],
        "review_status": "pending_review",
        "canary_status": "not_started",
        "patch_only": True,
        "legacy_compatibility": False,
    }
    with _lock:
        rows = _read(output_root)
        rows.append(row)
        _write(output_root, rows)
    return row


def list_proposals(output_root: Path, *, status: str = "") -> list[dict[str, Any]]:
    rows = _read(output_root)
    return [x for x in rows if not status or x.get("status") == status]


def current_version(output_root: Path, stage: str) -> str:
    rows = _version_rows(output_root)
    matches = [x for x in rows if x.get("stage") == str(stage).upper().strip() and x.get("active")]
    return str(matches[-1].get("version", "v0000")) if matches else "v0000"


def list_versions(output_root: Path, stage: str = "") -> list[dict[str, Any]]:
    stage = str(stage).upper().strip()
    rows = _version_rows(output_root)
    return [x for x in rows if not stage or x.get("stage") == stage]


def _publish_version(
    output_root: Path,
    stage: str,
    prompt: str,
    *,
    reason: str,
    source: str,
    scope: Mapping[str, Any] | None = None,
    source_proposal_id: str = "",
    rollback_from: str = "",
) -> dict[str, Any]:
    stage = str(stage).upper().strip()
    prior = current_version(output_root, stage)
    existing = list_versions(output_root, stage)
    number = max([int(str(x.get("version", "v0000"))[1:]) for x in existing] or [0]) + 1
    version = f"v{number:04d}"
    version_dir = _versions_root() / stage
    version_dir.mkdir(parents=True, exist_ok=True)
    version_file = version_dir / f"{version}.md"
    version_file.write_text(prompt, encoding="utf-8")
    target = _versions_root().parent / f"{stage}.md"
    original = target.read_text(encoding="utf-8")
    marker, end = "<!-- prompt: system -->", "<!-- /prompt -->"
    start = original.index(marker) + len(marker)
    finish = original.index(end, start)
    target.write_text(original[:start] + "\n" + prompt + "\n" + original[finish:], encoding="utf-8")
    rows = _read(output_root)
    for row in rows:
        if row.get("record_type") == "version" and row.get("stage") == stage:
            row["active"] = False
    record = {"record_type": "version", "stage": stage, "version": version, "parent_version": prior, "active": True, "created_at": _now(), "reason": reason, "source": source, "source_proposal_id": str(source_proposal_id or "")[:200], "scope": dict(scope or {}), "rollback_from": str(rollback_from or "")[:32], "file": _relative_project_path(version_file), "file_hash": _text_hash(prompt)}
    rows.append(record)
    _write(output_root, rows)
    invalidate_dynamic_winning_prompt_cache()
    return record


def rollback_version(
    *,
    output_root: Path,
    stage: str,
    version: str,
    reviewer: str,
    comment: str = "",
    allow_scoped_publish: bool = False,
) -> dict[str, Any]:
    stage = str(stage).upper().strip()
    version = str(version).lower().strip()
    rows = list_versions(output_root, stage)
    found = next((x for x in rows if x.get("version") == version), None)
    if found is None:
        raise KeyError("version not found")
    # Version rows normally point back to the proposal that produced them.
    # Resolve that source before touching the live Prompt so a scoped
    # candidate cannot be reintroduced through the rollback endpoint either.
    source_id = str(
        found.get("source_proposal_id") or found.get("source", "")
    ).strip()
    source = next(
        (
            item
            for item in _read(Path(output_root))
            if item.get("proposal_id") == source_id
        ),
        None,
    )
    scoped_source = (
        proposal_scope_requires_global_publish(found)
        or proposal_scope_requires_global_publish(source)
    )
    scoped_publish_authorized = (
        str(reviewer or "").strip().lower() == "admin"
        and bool(allow_scoped_publish)
    )
    if scoped_source and not scoped_publish_authorized:
        raise ValueError(
            "scoped prompt version cannot publish shared active prompt; "
            "global admin with cross-scope authorization is required"
        )
    prompt_file = Path(str(found.get("file", "")))
    if not prompt_file.is_absolute():
        prompt_file = _project_root() / prompt_file
    if not prompt_file.is_file():
        raise FileNotFoundError("version snapshot is missing")
    content = prompt_file.read_text(encoding="utf-8")
    if str(found.get("snapshot_format", "")).strip() == "markdown":
        records = _publish_sources_atomic(
            output_root,
            {stage: content},
            reason=f"rollback to {version}: {comment}"[:2000],
            source=f"rollback:{reviewer}",
            scope=found.get("scope") if isinstance(found.get("scope"), Mapping) else {},
            source_proposal_id=str(
                found.get("source_proposal_id") or found.get("source", "")
            )[:200],
            rollback_from=version,
        )
        record = records[-1]
    else:
        record = _publish_version(
            output_root,
            stage,
            content,
            reason=f"rollback to {version}: {comment}"[:2000],
            source=f"rollback:{reviewer}",
            scope=found.get("scope") if isinstance(found.get("scope"), Mapping) else {},
            source_proposal_id=str(
                found.get("source_proposal_id") or found.get("source", "")
            )[:200],
            rollback_from=version,
        )
    return record


def _replay_gate_passed(row: Mapping[str, Any]) -> bool:
    """Return whether a proposal carries an explicit passing replay gate."""

    refs = row.get("replay_refs")
    if not isinstance(refs, (list, tuple, set)) or not any(str(item).strip() for item in refs):
        return False
    if str(row.get("evaluation_status", "")).strip().lower() != "completed":
        return False
    # Promotion must consume the canonical persisted gate, not a truthy bit
    # supplied by a caller.  Requiring an object, the literal boolean ``True``,
    # and an exact ``pass`` verdict prevents values such as ``"ok"`` or a
    # mismatched/omitted verdict from opening the approval path.
    gate = row.get("replay_gate")
    if not isinstance(gate, Mapping):
        return False
    if gate.get("passed") is not True:
        return False
    if str(gate.get("verdict", "")).strip().lower() != "pass":
        return False

    # The summary is the evidence envelope validated at attachment time.  A
    # ledger row can be edited or constructed directly, so revalidate it here
    # before treating the proposal as replay-approved.  Missing/invalid
    # summaries fail closed and remain reviewable only after a fresh replay.
    summary = row.get("replay_summary")
    if not isinstance(summary, Mapping):
        return False
    evaluation_id = str(
        row.get("evaluation_id") or summary.get("eval_id") or ""
    ).strip()
    if not evaluation_id:
        return False
    try:
        strict_provenance, expected_parent, expected_candidates = _proposal_replay_identity(row)
        _validate_replay_evidence(
            summary,
            evaluation_id=evaluation_id,
            require_pass=True,
            expected_parent_bundle_hash=expected_parent,
            expected_candidate_prompt_hashes=expected_candidates,
            strict_provenance=strict_provenance,
        )
    except (TypeError, ValueError, KeyError):
        return False
    summary_gate = summary.get("gate")
    if not isinstance(summary_gate, Mapping):
        return False
    return (
        summary_gate.get("passed") is True
        and str(summary_gate.get("verdict", "")).strip().lower() == "pass"
    )


def _hash_text(value: Any, *, field: str) -> str:
    """Normalize and validate a replay fixture/hash identity.

    Replay summaries are an API boundary, so accepting an arbitrary string
    here would let a caller attach a plausible-looking ``gate.passed`` bit
    without binding the decision to an immutable fixture.  Both the sidecar's
    plain 64-hex hashes and the documented ``sha256:`` form are accepted.
    """

    text = str(value or "").strip().lower()
    if text.startswith("sha256:"):
        text = text[7:]
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise ValueError(f"{field} must be a SHA-256 hash")
    return text


def _normalise_replay_hash_map(
    value: Any,
    *,
    field: str,
) -> dict[str, str]:
    """Normalize a stage-to-prompt hash map from replay evidence.

    Prompt evolution ledgers use canonical stage names (``S1``--``S6`` and
    ``common``), while external evaluators occasionally emit lower-case stage
    keys.  Normalizing at this boundary keeps comparisons deterministic and
    prevents a spelling variation from bypassing candidate identity checks.
    """

    if value in (None, "", {}):
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    result: dict[str, str] = {}
    for raw_stage, raw_hash in value.items():
        try:
            stage = _prompt_key(raw_stage)
        except ValueError as exc:
            raise ValueError(f"{field} contains an invalid stage: {raw_stage}") from exc
        if stage in result:
            raise ValueError(f"{field} contains duplicate stage: {stage}")
        result[stage] = _hash_text(raw_hash, field=f"{field}.{stage}")
    return result


def _replay_identity_values(
    value: Mapping[str, Any],
    *,
    field: str,
) -> tuple[str, dict[str, str]]:
    """Extract immutable Bundle and candidate Prompt identities.

    ``bundle_id`` is an opaque compatibility label in historical summaries.
    Explicit hash fields are preferred; a ``bundle_id`` is treated as an
    identity only when it itself is a valid SHA-256 value.  This allows old
    benchmark reports (for example ``bundle-1``) to remain attachable to
    legacy proposals without weakening governed patch proposals.
    """

    containers: list[tuple[str, Mapping[str, Any]]] = [(field, value)]
    metadata = value.get("metadata")
    if isinstance(metadata, Mapping):
        containers.append((f"{field}.metadata", metadata))

    # Explicit parent fields have precedence over generic aliases.  A replay
    # producer may also emit ``prompt_bundle_hash`` for the *candidate* arm;
    # treating that as a second parent would incorrectly reject an otherwise
    # well-bound summary.
    explicit_identities: list[tuple[str, str]] = []
    generic_identities: list[tuple[str, str]] = []
    candidate_maps: list[tuple[str, dict[str, str]]] = []
    for container_field, container in containers:
        for key in (
            "parent_bundle_hash",
            "baseline_bundle_hash",
            "parent_prompt_bundle_hash",
        ):
            raw = container.get(key)
            if raw in (None, ""):
                continue
            explicit_identities.append(
                (
                    f"{container_field}.{key}",
                    _hash_text(raw, field=f"{container_field}.{key}"),
                )
            )
        for key in ("prompt_bundle_hash", "bundle_hash"):
            raw = container.get(key)
            if raw in (None, ""):
                continue
            generic_identities.append(
                (
                    f"{container_field}.{key}",
                    _hash_text(raw, field=f"{container_field}.{key}"),
                )
            )
        # ``bundle_id`` remains useful when a producer uses the parent hash as
        # its bundle label.  Ignore opaque labels rather than rejecting legacy
        # summaries; strict patch validation below still requires an actual
        # cryptographic identity.
        raw_bundle_id = container.get("bundle_id")
        if raw_bundle_id not in (None, ""):
            text = str(raw_bundle_id).strip()
            if _SHA256_RE.fullmatch(text):
                generic_identities.append(
                    (
                        f"{container_field}.bundle_id",
                        _hash_text(text, field=f"{container_field}.bundle_id"),
                    )
                )
        for key in ("candidate_prompt_hashes", "prompt_hashes"):
            raw_map = container.get(key)
            if raw_map in (None, ""):
                continue
            candidate_maps.append(
                (
                    f"{container_field}.{key}",
                    _normalise_replay_hash_map(
                        raw_map,
                        field=f"{container_field}.{key}",
                    ),
                )
            )

    identities = explicit_identities or generic_identities
    identity_values = {identity for _, identity in identities}
    if len(identity_values) > 1:
        raise ValueError(f"{field} contains conflicting bundle identities")
    identity = next(iter(identity_values), "")

    candidate_hashes: dict[str, str] = {}
    for source, mapping in candidate_maps:
        for stage, digest in mapping.items():
            prior = candidate_hashes.get(stage)
            if prior is not None and prior != digest:
                raise ValueError(f"{field} contains conflicting candidate prompt hashes")
            candidate_hashes[stage] = digest
    return identity, candidate_hashes


def _proposal_replay_identity(
    proposal: Mapping[str, Any] | None,
) -> tuple[bool, str, dict[str, str]]:
    """Return strict replay identity requirements for a Prompt proposal."""

    if not isinstance(proposal, Mapping):
        return False, "", {}
    # Legacy full-file records are intentionally kept compatible.  Governed
    # section-patch records, on the other hand, must prove that replay ran
    # against this exact parent Bundle and candidate Prompt content.
    strict = bool(proposal.get("patch_only")) and not bool(
        proposal.get("legacy_compatibility", False)
    )
    if not strict:
        return False, "", {}
    raw_parent = proposal.get("parent_bundle_hash")
    if raw_parent in (None, ""):
        # Keep hand-authored historical rows readable.  Newly generated
        # section-patch proposals always carry a valid hash; rows without one
        # are treated as legacy and cannot opt into strict provenance checks.
        return False, "", {}
    try:
        parent = _hash_text(raw_parent, field="proposal.parent_bundle_hash")
    except ValueError:
        return False, "", {}
    candidate = _normalise_replay_hash_map(
        proposal.get("candidate_prompt_hashes"),
        field="proposal.candidate_prompt_hashes",
    )
    return True, parent, candidate


def _replay_arm_list(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        raise ValueError(f"{field} must be a list")
    result = [str(item).strip().lower() for item in value if str(item).strip()]
    if len(result) != len(set(result)):
        raise ValueError(f"{field} must not contain duplicate arms")
    unknown = sorted(set(result) - _REPLAY_ARMS)
    if unknown:
        raise ValueError(f"{field} contains unsupported arms: {unknown}")
    return result


def _validate_replay_evidence(
    replay_summary: Mapping[str, Any],
    *,
    evaluation_id: str,
    require_pass: bool,
    expected_parent_bundle_hash: str = "",
    expected_candidate_prompt_hashes: Mapping[str, Any] | None = None,
    strict_provenance: bool = False,
) -> dict[str, Any]:
    """Validate the replay wire contract before storing evidence.

    The evaluator remains responsible for producing the detailed artifact;
    this bounded check protects the approval ledger from hand-written or
    partially paired summaries.  It intentionally validates identities and
    completeness, not deployment-specific metric thresholds.
    """

    summary = dict(replay_summary)
    if str(summary.get("schema_version", "")).strip() != "1.0":
        raise ValueError("replay summary schema_version must be 1.0")
    summary_eval_id = str(summary.get("eval_id", "")).strip()
    if not summary_eval_id:
        raise ValueError("replay summary eval_id is required")
    if summary_eval_id != str(evaluation_id).strip():
        raise ValueError("replay evaluation_id does not match summary eval_id")

    expected_arms = _replay_arm_list(summary.get("expected_arms"), field="expected_arms")
    observed_arms = _replay_arm_list(summary.get("observed_arms"), field="observed_arms")
    if not _REPLAY_REQUIRED_ARMS.issubset(expected_arms):
        raise ValueError("replay expected_arms must include prompt_only, memory_only and both")
    if not _REPLAY_REQUIRED_ARMS.issubset(observed_arms):
        raise ValueError("replay observed_arms must include prompt_only, memory_only and both")
    candidate = str(summary.get("candidate_arm", "")).strip().lower()
    reference = str(summary.get("reference_arm", "")).strip().lower()
    if candidate not in observed_arms or reference not in observed_arms or candidate == reference:
        raise ValueError("replay candidate/reference arms are invalid")

    fixture = summary.get("fixture")
    if not isinstance(fixture, Mapping):
        raise ValueError("replay fixture metadata is required")
    fixture_hash = _hash_text(fixture.get("fixture_sha256"), field="fixture.fixture_sha256")
    snapshot_hash = fixture.get("dataset_snapshot")
    if snapshot_hash not in (None, "") and _hash_text(snapshot_hash, field="fixture.dataset_snapshot") != fixture_hash:
        raise ValueError("replay fixture hash mismatch: dataset_snapshot does not match fixture_sha256")
    raw_query_ids = fixture.get("query_ids")
    if not isinstance(raw_query_ids, (list, tuple, set, frozenset)):
        raise ValueError("replay fixture query_ids are required")
    query_ids = [str(item).strip() for item in raw_query_ids if str(item).strip()]
    if not query_ids or len(query_ids) != len(set(query_ids)):
        raise ValueError("replay fixture query_ids must be non-empty and unique")
    try:
        fixture_count = int(fixture.get("query_count"))
        query_count = int(summary.get("query_count"))
        complete_count = int(summary.get("complete_case_count"))
    except (TypeError, ValueError) as exc:
        raise ValueError("replay query counts must be integers") from exc
    if fixture_count != len(query_ids) or query_count != fixture_count:
        raise ValueError("replay fixture/query_count mismatch")
    if complete_count != query_count:
        raise ValueError("replay complete_case_count must equal fixture query_count")
    missing_pairs = summary.get("missing_pairs", {})
    if not isinstance(missing_pairs, Mapping) or missing_pairs:
        raise ValueError("replay contains incomplete query/arm pairs")

    # Each required arm must cover every fixed Query.  This catches summaries
    # whose top-level counts were edited while an arm denominator remained
    # incomplete.
    arm_summaries = summary.get("arms")
    if not isinstance(arm_summaries, Mapping):
        raise ValueError("replay arm summaries are required")
    for arm in expected_arms:
        if arm not in arm_summaries:
            raise ValueError(f"replay arm summary is missing: {arm}")
        try:
            arm_count = int(arm_summaries[arm].get("query_count"))
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError(f"replay arm query_count is invalid: {arm}") from exc
        if arm_count != query_count:
            raise ValueError(f"replay arm is not fully paired: {arm}")

    manifest = summary.get("manifest")
    if not isinstance(manifest, Mapping):
        raise ValueError("replay manifest is required")
    if str(manifest.get("eval_id", "")).strip() not in {"", summary_eval_id}:
        raise ValueError("replay manifest eval_id does not match summary")
    manifest_hash = _hash_text(manifest.get("fixture_sha256"), field="manifest.fixture_sha256")
    if manifest_hash != fixture_hash:
        raise ValueError("replay manifest fixture hash does not match fixture metadata")
    dataset_snapshot = manifest.get("dataset_snapshot")
    if dataset_snapshot not in (None, "") and _hash_text(dataset_snapshot, field="manifest.dataset_snapshot") != fixture_hash:
        raise ValueError("replay manifest dataset snapshot does not match fixture hash")
    manifest_ids = manifest.get("query_ids")
    if manifest_ids is not None and [str(item).strip() for item in manifest_ids] != query_ids:
        raise ValueError("replay manifest query_ids do not match fixture")
    if manifest.get("query_count") not in (None, fixture_count):
        raise ValueError("replay manifest query_count does not match fixture")
    manifest_arms = _replay_arm_list(
        manifest.get("arms"), field="manifest.arms"
    )
    if not _REPLAY_REQUIRED_ARMS.issubset(manifest_arms):
        raise ValueError(
            "replay manifest arms must include prompt_only, memory_only and both"
        )
    if not set(expected_arms).issubset(manifest_arms):
        raise ValueError("replay manifest arms do not cover summary expected_arms")

    # Bind replay evidence to the exact Prompt Bundle used to produce it.  The
    # historical ``bundle_id`` is intentionally opaque; new evaluators should
    # emit ``parent_bundle_hash`` (and, when available, stage-level candidate
    # hashes) in the manifest or summary.  Only governed section-patch
    # proposals enable the strict requirement, preserving compatibility for
    # old full-file proposals and benchmark reports that used labels such as
    # ``bundle-1``.
    if expected_parent_bundle_hash or strict_provenance:
        try:
            expected_parent = _hash_text(
                expected_parent_bundle_hash,
                field="proposal.parent_bundle_hash",
            )
        except ValueError:
            # A legacy/manual patch record may carry a placeholder such as
            # ``sha256:parent``.  It cannot be compared cryptographically, so
            # retain the historical permissive behavior.  Generated
            # section-patch proposals always use a valid SHA-256 value and
            # therefore still take the strict path.
            expected_parent = ""
            strict_provenance = False
        summary_parent, observed_candidate_hashes = _replay_identity_values(
            summary,
            field="replay summary",
        )
        manifest_parent, manifest_candidate_hashes = _replay_identity_values(
            manifest,
            field="replay manifest",
        )
        parent_identity = summary_parent or manifest_parent
        if expected_parent:
            if not parent_identity:
                raise ValueError(
                    "replay manifest parent_bundle_hash is required for patch proposal"
                )
            if parent_identity != expected_parent:
                raise ValueError(
                    "replay manifest bundle identity does not match proposal parent_bundle_hash"
                )
            # If both envelopes carry an identity, they must agree as well;
            # otherwise a caller could splice a valid manifest onto a summary
            # generated from a different Bundle.
            if summary_parent and manifest_parent and summary_parent != manifest_parent:
                raise ValueError(
                    "replay summary/manifest bundle identities do not match"
                )
        expected_candidates = _normalise_replay_hash_map(
            expected_candidate_prompt_hashes,
            field="proposal.candidate_prompt_hashes",
        )
        observed_candidates: dict[str, str] = {}
        for candidate_map in (observed_candidate_hashes, manifest_candidate_hashes):
            for stage, digest in candidate_map.items():
                prior = observed_candidates.get(stage)
                if prior is not None and prior != digest:
                    raise ValueError(
                        "replay summary/manifest candidate prompt hashes do not match"
                    )
                observed_candidates[stage] = digest
        if expected_candidates and observed_candidates:
            # Candidate hashes are optional evidence because older replay
            # workers may only persist the parent Bundle identity.  Compare
            # the intersection when a worker does provide hashes; do not
            # reject an otherwise valid replay solely because an unaffected
            # stage was omitted from its summary.
            mismatched = sorted(
                stage
                for stage in set(expected_candidates).intersection(observed_candidates)
                if observed_candidates.get(stage) != expected_candidates[stage]
            )
            if mismatched:
                raise ValueError(
                    "replay candidate prompt hash mismatch: "
                    + ", ".join(mismatched)
                )
        # Candidate Prompt hashes are an additive field.  Some evaluators can
        # only report the parent Bundle identity (for example, when the
        # candidate is materialized in an isolated worker); in that case the
        # parent binding remains mandatory but the optional stage-level check
        # is skipped.  Whenever hashes are present on both sides, however,
        # every declared stage must match exactly.

    gate = summary.get("gate")
    if not isinstance(gate, Mapping):
        raise ValueError("replay gate is required")
    passed = gate.get("passed") is True or str(gate.get("passed", "")).strip().lower() in {"true", "pass", "passed", "ok"}
    verdict = str(gate.get("verdict", summary.get("verdict", ""))).strip().lower()
    reasons = gate.get("reasons", [])
    if reasons not in (None, "") and (not isinstance(reasons, (list, tuple, set, frozenset)) or any(str(item).strip() for item in reasons)):
        raise ValueError("replay gate contains failure reasons")
    if require_pass and (not passed or verdict != "pass"):
        raise ValueError("replay gate has not passed")
    if require_pass and str(summary.get("verdict", "")).strip().lower() not in {"", "pass", "passed"}:
        raise ValueError("replay summary verdict has not passed")
    return {
        "fixture_sha256": fixture_hash,
        "query_ids": query_ids,
        "query_count": query_count,
        "expected_arms": expected_arms,
        "observed_arms": observed_arms,
        "parent_bundle_hash": (
            _hash_text(expected_parent_bundle_hash, field="proposal.parent_bundle_hash")
            if expected_parent_bundle_hash and _SHA256_RE.fullmatch(str(expected_parent_bundle_hash).strip())
            else ""
        ),
    }


def validate_proposal_for_review(
    row: Mapping[str, Any],
    *,
    require_replay: bool = False,
) -> dict[str, Any]:
    """Validate static contracts and (optionally) the replay-first gate."""

    errors: list[str] = []
    manifest = validate_section_manifest()
    if not manifest.get("ok"):
        errors.extend(str(item) for item in manifest.get("errors", []))
    patches = row.get("section_patches", [])
    if not isinstance(patches, list) or not patches:
        errors.append("section_patches are required")
    static = row.get("static_checks", {})
    if require_replay:
        if row.get("legacy_compatibility") and not row.get("patch_only"):
            # A legacy full-file replacement has no trustworthy proof that
            # protected leaf contracts were preserved.  Do not silently turn
            # its historical ``not_run`` markers into a pass merely because a
            # replay artifact was attached; require migration to a governed
            # section patch instead.
            errors.append("legacy_full_section_requires_section_patch")
        if not isinstance(static, Mapping):
            errors.append("static_checks are missing")
        else:
            for key in ("schema", "manifest", "mutable_sections", "protected_sections", "compare_and_swap"):
                value = str(static.get(key, "")).strip().lower()
                if value not in {"pass", "passed", "ok", "true"}:
                    errors.append(f"static_check_failed:{key}")
        if not _replay_gate_passed(row):
            errors.append("replay_gate_not_passed")
        stages = {str(item).upper().strip() for item in row.get("stages", [])}
        impacted = {str(item).upper().strip() for item in row.get("impacted_stages", [])}
        if stages.intersection({"S3", "S4"}) and not {"S3", "S4"}.issubset(impacted):
            errors.append("s3_s4_coupled_replay_required")
    return {"ok": not errors, "errors": errors, "replay_gate_passed": _replay_gate_passed(row)}


def proposal_scope_requires_global_publish(row: Mapping[str, Any] | None) -> bool:
    """Return whether publishing ``row`` would cross a tenant boundary.

    Prompt files in ``agents/prompts/dynamic_winning`` are deployment-wide
    resources.  A proposal may still be created, replayed, and reviewed in a
    tenant/workspace namespace, but writing its candidate into those shared
    files is a platform-level operation.  Keep this check at the domain layer
    as well as the HTTP boundary so direct CLI/library callers cannot bypass
    the API authorization check.  Legacy ledgers stored scope fields either
    at the top level or under ``scope``; both forms are handled here.

    ``route`` is included deliberately: a route-only challenger is still a
    scoped candidate and must not silently alter the deployment-wide bundle.
    Empty/legacy records remain compatible with the historical local review
    flow.
    """

    source = row if isinstance(row, Mapping) else {}
    nested = source.get("scope")
    nested = nested if isinstance(nested, Mapping) else {}
    for key in ("tenant_id", "workspace_id", "project_id", "profile_id", "route"):
        if str(source.get(key) or nested.get(key, "")).strip():
            return True
    stages = source.get("stage_scope")
    if stages in (None, "", [], (), set(), frozenset()):
        stages = nested.get("stage_scope", [])
    if isinstance(stages, (list, tuple, set, frozenset)):
        return any(str(item).strip() for item in stages if item is not None)
    return bool(str(stages or "").strip())


def review_proposal(
    *,
    output_root: Path,
    proposal_id: str,
    decision: str,
    reviewer: str,
    comment: str = "",
    require_replay: bool = False,
    allow_scoped_publish: bool = False,
) -> dict[str, Any]:
    decision = str(decision).lower().strip()
    if decision not in {"approved", "rejected"}:
        raise ValueError("decision must be approved or rejected")
    # ``allow_scoped_publish`` is an authorization result computed by the
    # API boundary.  Require the domain reviewer identity to be ``admin`` as
    # a second line of defence for direct library/CLI callers that might pass
    # the boolean accidentally or from an untrusted integration.
    scoped_publish_authorized = bool(
        allow_scoped_publish and str(reviewer or "").strip().lower() == "admin"
    )
    with _lock:
        rows = _read(output_root)
        for row in rows:
            if row.get("proposal_id") != proposal_id:
                continue
            if (
                decision == "approved"
                and str(row.get("effect_status", "")).strip().lower()
                in _IMMUTABLE_PROMPT_EFFECT_STATUSES
            ):
                raise ValueError(
                    "superseded or withdrawn proposal cannot be approved or published"
                )
            # A tenant-scoped candidate may be reviewed and approved for its
            # own audit trail, but it cannot mutate the deployment-wide
            # dynamic-winner files.  Keep that approval retryable: a platform
            # administrator can later re-submit the same proposal with an
            # explicit cross-scope authorization and publish it deliberately.
            deferred_scoped = (
                row.get("status") == "approved"
                and row.get("publish_status") == "deferred_scoped"
            )
            if row.get("status") != "pending_review" and not (
                deferred_scoped and decision == "approved" and scoped_publish_authorized
            ):
                raise ValueError("proposal has already been reviewed")
            if decision == "approved":
                validation = validate_proposal_for_review(
                    row,
                    require_replay=require_replay,
                )
                if require_replay and not validation["ok"]:
                    raise ValueError(
                        "replay-first review gate failed: "
                        + ", ".join(validation["errors"])
                    )
                scoped = proposal_scope_requires_global_publish(row)
                can_publish = (not scoped) or scoped_publish_authorized
                if can_publish:
                    if row.get("patch_only") and isinstance(row.get("after_sources"), Mapping):
                        _publish_sources_atomic(
                            output_root,
                            row["after_sources"],
                            reason="approved prompt evolution section patch",
                            source=row["proposal_id"],
                            scope=row.get("scope") if isinstance(row.get("scope"), Mapping) else {},
                            source_proposal_id=str(row["proposal_id"]),
                            expected_parent_bundle_hash=(
                                str(row.get("parent_bundle_hash", "")).strip()
                                if require_replay
                                else ""
                            ),
                        )
                    else:
                        for stage, prompt in row["after"].items():
                            _publish_version(
                                output_root,
                                stage,
                                prompt,
                                reason="approved prompt evolution proposal",
                                source=row["proposal_id"],
                                scope=row.get("scope") if isinstance(row.get("scope"), Mapping) else {},
                                source_proposal_id=str(row["proposal_id"]),
                            )
                # Each publish appends a version record to the ledger.  Reload
                # after publishing so the final proposal update cannot
                # overwrite those records with the stale pre-publish list.
                rows = _read(output_root)
                row = next(
                    item
                    for item in rows
                    if item.get("proposal_id") == proposal_id
                )
                row["status"] = "approved"
                row["effect_status"] = "pending_validation"
                row["publish_status"] = (
                    "published" if can_publish else "deferred_scoped"
                )
                if not can_publish:
                    row["publish_deferred_reason"] = (
                        "scoped proposal requires global admin with "
                        "X-Evolution-Cross-Scope=true to publish shared active prompt"
                    )
                else:
                    row.pop("publish_deferred_reason", None)
            else:
                row["status"] = "rejected"
                row["publish_status"] = "not_published"
            row.update({"reviewer": str(reviewer), "review_comment": str(comment)[:2000], "reviewed_at": _now(), "updated_at": _now()})
            _write(output_root, rows)
            return row
    raise KeyError("proposal not found")


def attach_replay_evidence(
    *,
    output_root: Path,
    proposal_id: str,
    evaluation_id: str,
    replay_summary: Mapping[str, Any],
    artifact_path: str | Path = "",
    evaluator_id: str = "",
    require_pass: bool = True,
) -> dict[str, Any]:
    """Attach a replay result before human approval.

    Replay output is copied as bounded JSON and referenced by a portable path;
    no model or evaluator can mutate the production Prompt from this call.
    ``review_proposal(require_replay=True)`` consumes the resulting gate.
    """

    key = str(proposal_id or "").strip()
    evaluation_key = str(evaluation_id or "").strip()
    if not key or not evaluation_key:
        raise ValueError("proposal_id and evaluation_id are required")
    if not isinstance(replay_summary, Mapping):
        raise ValueError("replay_summary must be an object")
    # Keep the persisted summary bounded.  The evaluator's detailed artifact
    # remains on disk and is linked by a portable path for audit/replay.
    encoded = json.dumps(dict(replay_summary), ensure_ascii=False, sort_keys=True)
    if len(encoded) > 12000:
        raise ValueError("replay summary is too large")
    with _lock:
        rows = _read(Path(output_root))
        target = next((row for row in rows if row.get("proposal_id") == key), None)
        if target is None:
            raise KeyError("proposal not found")
        if target.get("status") != "pending_review":
            raise ValueError("replay evidence must be attached before review")
        # Validate after resolving the proposal so governed section patches
        # can bind their replay evidence to the immutable parent Bundle and
        # candidate Prompt hashes.  Legacy full-file proposals intentionally
        # retain the historical fixture-only validation contract.
        strict_provenance, expected_parent, expected_candidates = _proposal_replay_identity(target)
        _validate_replay_evidence(
            replay_summary,
            evaluation_id=evaluation_key,
            require_pass=require_pass,
            expected_parent_bundle_hash=expected_parent,
            expected_candidate_prompt_hashes=expected_candidates,
            strict_provenance=strict_provenance,
        )
        gate = replay_summary.get("gate", {})
        refs = [str(item) for item in target.get("replay_refs", []) if str(item).strip()]
        if evaluation_key not in refs:
            refs.append(evaluation_key)
        target["replay_refs"] = refs[-16:]
        target["replay_gate"] = dict(gate) if isinstance(gate, Mapping) else {}
        target["replay_summary"] = dict(replay_summary)
        target["evaluation_status"] = "completed"
        target["evaluation_id"] = evaluation_key
        target["evaluation_metrics"] = dict(replay_summary.get("metrics", {})) if isinstance(replay_summary.get("metrics", {}), Mapping) else {}
        target["replay_evaluator_id"] = str(evaluator_id or "")[:160]
        if artifact_path:
            target["replay_artifact"] = _relative_project_path(Path(artifact_path))
        target["updated_at"] = _now()
        _write(Path(output_root), rows)
        return dict(target)


def update_proposal_effect_status(
    *,
    output_root: Path,
    proposal_id: str,
    effect_status: str,
    evaluator_id: str = "",
    evaluation_id: str = "",
    reason: str = "",
    metrics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Record replay/adjudication evidence for an approved prompt proposal.

    Approval publishes a candidate but does not assert that it improved
    production quality.  This explicit second step makes promotion evidence
    auditable and prevents pending proposals from being treated as effective.
    ``metrics`` is copied as bounded JSON data for dashboards/audits; it is not
    interpreted here because metric policies differ by deployment.
    """
    status = str(effect_status or "").strip().lower()
    if status not in PROMPT_EFFECT_STATUSES:
        raise ValueError("effect_status must be a terminal validation status")
    key = str(proposal_id or "").strip()
    if not key:
        raise ValueError("proposal_id is required")
    with _lock:
        rows = _read(Path(output_root))
        target = next((row for row in rows if row.get("proposal_id") == key), None)
        if target is None:
            raise KeyError("proposal not found")
        if target.get("status") != "approved":
            raise ValueError("only approved proposals can be evaluated")
        prior_status = str(
            target.get("effect_status") or "pending_validation"
        ).strip().lower()
        # Check lifecycle eligibility before requiring evaluator metadata.  A
        # pending proposal should retain the stable "only approved" error;
        # approved transitions remain fail-closed without explicit evidence.
        evaluator, evaluation = _require_effect_evidence(evaluator_id, evaluation_id)
        prior_evaluator = str(target.get("effect_evaluator_id") or "").strip()[:160]
        prior_evaluation = str(target.get("effect_evaluation_id") or "").strip()[:160]
        same_evidence_retry = (
            prior_status == status
            and prior_evaluator == evaluator
            and prior_evaluation == evaluation
        )
        # Never let a delayed/replayed callback revive a candidate that was
        # explicitly superseded or withdrawn.  The exact same terminal write
        # is idempotent, which is important for at-least-once evaluator jobs.
        _guard_effect_transition(
            prior_status,
            status,
            prior_evaluator_id=prior_evaluator,
            prior_evaluation_id=prior_evaluation,
            next_evaluation_id=evaluation,
            next_evaluator_id=evaluator,
        )
        if same_evidence_retry:
            return dict(target)
        updated_at = _now()
        clean_reason = str(reason or "")[:2000]
        target["effect_status"] = status
        target["evaluation_status"] = "completed"
        target["effect_evaluator_id"] = evaluator
        target["effect_evaluation_id"] = evaluation
        target["effect_reason"] = clean_reason
        target["evaluation_metrics"] = dict(metrics or {})
        target["effect_evidence"] = {
            "evaluator_id": evaluator,
            "evaluation_id": evaluation,
            "reason": clean_reason,
            "recorded_at": updated_at,
        }
        history = target.get("effect_history")
        if not isinstance(history, list):
            history = []
        history.append(
            {
                "from_status": prior_status,
                "to_status": status,
                "evaluator_id": evaluator,
                "evaluation_id": evaluation,
                "reason": clean_reason,
                "recorded_at": updated_at,
            }
        )
        target["effect_history"] = history[-32:]
        target["effect_updated_at"] = updated_at
        target["updated_at"] = target["effect_updated_at"]
        _write(Path(output_root), rows)
        return dict(target)


async def propose_with_codex(
    *,
    project_root: Path,
    output_root: Path,
    feedback: Mapping[str, Any],
    stages: list[str],
    provider: Any,
) -> dict[str, Any]:
    """Ask Codex for a governed section patch, with a legacy fallback.

    New challengers are deliberately section-scoped.  A model that still
    follows the historical ``{"prompts": {stage: full_text}}`` contract is
    accepted for compatibility, but the resulting proposal is marked legacy
    by :func:`create_proposal` and therefore cannot pass replay-first review
    until it is migrated to ``section_patches``.
    """

    selected = [
        str(stage).upper().strip()
        for stage in stages
        if str(stage).upper().strip() in STAGES
    ] or ["S3", "S4", "S5", "S6"]

    # Give the challenger the current mutable leaves and their hashes rather
    # than a full production Prompt bundle.  This reduces prompt injection
    # surface and makes the requested output directly consumable by the
    # section-level compare-and-swap validator.
    mutable_sections: dict[str, dict[str, dict[str, str]]] = {}
    for stage in selected:
        _, sections, _ = _read_prompt_sections(stage)
        rows: dict[str, dict[str, str]] = {}
        for section_id, text in sections.items():
            mutable, protected = _section_policy(stage, section_id)
            if mutable and not protected:
                rows[section_id] = {
                    "old_hash": _section_hash(text),
                    "text": text,
                }
        mutable_sections[stage] = rows

    request = {
        "task": (
            "根据审核反馈提出最小、可回放的动态蜂群 Prompt section patch。"
            "优先返回 section_patches，不要替换完整 Prompt 文件；保留输出契约、"
            "证据边界、候选身份冻结、安全边界和阶段职责，不改变 S1-S6 接口字段。"
        ),
        "feedback": dict(feedback),
        "stages": selected,
        "mutable_sections": mutable_sections,
        "output_contract": {
            "preferred": {
                "section_patches": [
                    {
                        "section_id": "S4:creative",
                        "old_hash": "sha256:<64 hex>",
                        "new_text": "新的 section 正文（至少 20 个字符）",
                        "rationale": "可证伪的修改理由",
                        "counterexamples": ["反例"],
                        "acceptance_tests": ["验收条件"],
                    }
                ],
                "hypothesis": "一个可证伪假设",
            },
            "legacy_compatibility": {
                "prompts": {"S4": "完整 Prompt 正文，仅供旧客户端回退"}
            },
        },
    }
    messages = [
        ModelMessage(
            role="system",
            content=(
                "你是受治理的提示词工程师。只提出最小、可审查、可回放的文本修改；"
                "优先使用 section_patches，禁止输出 Markdown 代码围栏。"
            ),
        ),
        ModelMessage(
            role="user", content=json.dumps(request, ensure_ascii=False)
        ),
    ]
    output_schema = {
        "type": "object",
        "properties": {
            "section_patches": {"type": "array"},
            "prompts": {"type": "object"},
            "hypothesis": {"type": "string"},
            "change_units": {"type": "array"},
            "target_metrics": {"type": "array"},
            "counterexamples": {"type": "array"},
            "acceptance_tests": {"type": "array"},
            "expected_tradeoffs": {"type": "object"},
        },
        # Do not make section_patches formally required: older Codex CLI
        # adapters may ignore the updated schema and return ``prompts``.
        "additionalProperties": False,
    }
    final = None
    async for event in provider.stream(
        messages,
        [],
        {
            "reasoning_effort": "medium",
            "output_schema": output_schema,
        },
    ):
        if event.event_type == "final":
            final = event.final_turn
    if final is None or not final.text:
        raise ValueError("Codex prompt evolution returned no final output")
    try:
        payload = json.loads(final.text)
    except (TypeError, ValueError) as exc:
        raise ValueError("Codex prompt evolution returned invalid JSON") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("Codex prompt evolution output must be a JSON object")

    raw_patches = payload.get("section_patches")
    if raw_patches not in (None, ""):
        if not isinstance(raw_patches, (list, tuple)) or not raw_patches:
            raise ValueError("section_patches must be a non-empty array")
        patch_stages = list(
            dict.fromkeys(
                _normalise_patch_section(
                    patch.get("section_id") or patch.get("id")
                )[0]
                for patch in raw_patches
                if isinstance(patch, Mapping)
            )
        )
        if not patch_stages:
            raise ValueError("section_patches must contain patch objects")
        return create_section_patch_proposal(
            output_root=output_root,
            feedback=feedback,
            stages=patch_stages,
            section_patches=list(raw_patches),
            agent="codex_prompt_evolution",
            hypothesis=str(payload.get("hypothesis", "")),
            change_units=_bounded_strings(payload.get("change_units"), limit=3),
            target_metrics=_bounded_strings(payload.get("target_metrics"), limit=16),
            counterexamples=_bounded_strings(payload.get("counterexamples"), limit=8),
            acceptance_tests=_bounded_strings(payload.get("acceptance_tests"), limit=12),
            expected_tradeoffs=(
                dict(payload.get("expected_tradeoffs", {}))
                if isinstance(payload.get("expected_tradeoffs", {}), Mapping)
                else {}
            ),
            tenant_id=str(feedback.get("tenant_id", "")),
            workspace_id=str(feedback.get("workspace_id", "")),
            project_id=str(feedback.get("project_id", "")),
            profile_id=str(feedback.get("profile_id", "")),
            route=str(feedback.get("route", "")),
            stage_scope=feedback.get("stage_scope", []),
        )

    # Legacy Codex CLI clients may still return complete stage Prompts.  Keep
    # that path explicit and auditable; replay-first review will reject it
    # until a human/evaluator migrates it to section patches.
    prompts = payload.get("prompts")
    if not isinstance(prompts, Mapping) or not prompts:
        raise ValueError("Codex output must include section_patches or prompts")
    return create_proposal(
        output_root=output_root,
        feedback=feedback,
        stages=selected,
        proposed_prompts=prompts,
        agent="codex_prompt_evolution",
        hypothesis=str(payload.get("hypothesis", "")),
        change_units=_bounded_strings(payload.get("change_units"), limit=3),
        target_metrics=_bounded_strings(payload.get("target_metrics"), limit=16),
        counterexamples=_bounded_strings(payload.get("counterexamples"), limit=8),
        acceptance_tests=_bounded_strings(payload.get("acceptance_tests"), limit=12),
        expected_tradeoffs=(
            dict(payload.get("expected_tradeoffs", {}))
            if isinstance(payload.get("expected_tradeoffs", {}), Mapping)
            else {}
        ),
    )


def propose_with_codex_sync(**kwargs: Any) -> dict[str, Any]:
    return asyncio.run(propose_with_codex(**kwargs))
