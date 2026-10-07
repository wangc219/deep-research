"""Pure winning handoff, candidate and portrait helpers shared by execution modes."""

from __future__ import annotations

import json
import os
import re
import unicodedata
from collections.abc import (
    Mapping,
    Sequence,
)
from hashlib import (
    sha256,
)
from typing import (
    Any,
)

from equipment_deep_research.agents.workflows.shared_context import (
    compact_prompt_value as _compact_prompt_value,
    query_combat_equipment_divergence_brief as _query_combat_equipment_divergence_brief,
)
from equipment_deep_research.agents.workflows.reporting_support import (
    _winning_primary_equipment_form,
)
from equipment_deep_research.agents.dynamic_prompt_resources import (
    load_dynamic_winning_json,
    load_dynamic_winning_prompt,
)
from equipment_deep_research.domain.models import (
    WinningHypothesis,
)
from equipment_deep_research.domain.capability_portrait import (
    CAPABILITY_PORTRAIT_MODULES,
    CAPABILITY_PORTRAIT_QUALITY_CONTRACT_VERSION,
    S6_DEFAULT_CODEX_CONCURRENCY,
    S6_MAX_CODEX_CONCURRENCY,
    capability_portrait_module_lengths,
    parse_capability_portrait_modules,
    short_capability_portrait_modules,
)

from equipment_deep_research.orchestration.winning_swarm import (
    winning_summary_language_issues,
)

S6_PORTRAIT_QUALITY_CONTRACT_VERSION = (
    CAPABILITY_PORTRAIT_QUALITY_CONTRACT_VERSION
)

def _structured_prompt_records(section: str) -> tuple[dict[str, str], ...]:
    """Load a reviewed JSON catalog from ``common.md`` without mutable aliases."""

    value = load_dynamic_winning_json("common", section=section)
    if not isinstance(value, list) or not all(
        isinstance(item, Mapping) for item in value
    ):
        raise ValueError(f"dynamic resource section must be a JSON object list: {section}")
    return tuple(
        {str(key): str(item_value) for key, item_value in item.items()}
        for item in value
    )


# Keep these names as compatibility surfaces while making common.md the only
# source of the model-facing naming and winning-dimension prose.
S3_S4_WEAPON_NAMING_TYPES: tuple[dict[str, str], ...] = _structured_prompt_records(
    "s3_s4.naming_types"
)
S3_S4_WINNING_DIMENSION_PACKS: tuple[dict[str, str], ...] = _structured_prompt_records(
    "s3_s4.dimension_packs"
)


def _s3_s4_dimension_assignments(
    seed: str,
    seat_keys: Sequence[str],
) -> dict[str, dict[str, str]]:
    """Return the legacy one-pack-per-seat compatibility mapping.

    This helper is retained for old checkpoints and audit fixtures whose
    contract expects distinct reviewed D1--D7 examples (including one D7
    source-forward reference).  It is *not* used by the dynamic-v2 production
    path: production calls :func:`_s3_s4_open_dimension_slots`, which gives
    every seat exactly three open containers and lets the model author the
    actual winning dimensions from the Query.  Keeping that distinction here
    prevents the compatibility surface from being mistaken for a hard
    production taxonomy.

    The compatibility mapping is derived only from the durable graph seed and
    seat ids; retries therefore reconstruct the same map deterministically.
    """
    seats = [str(value) for value in seat_keys]
    if len(seats) > len(S3_S4_WINNING_DIMENSION_PACKS):
        raise ValueError("at most seven S3/S4 dimension seats are supported")
    if len(set(seats)) != len(seats):
        raise ValueError("seat_keys must be unique")
    if not seats:
        return {}
    ranked_seats = sorted(
        seats,
        key=lambda value: sha256(
            f"{seed}|dimension-seat|{value}".encode()
        ).digest(),
    )
    mandatory = [
        item for item in S3_S4_WINNING_DIMENSION_PACKS if item["code"] == "D7"
    ]
    optional = [
        item for item in S3_S4_WINNING_DIMENSION_PACKS if item["code"] != "D7"
    ]
    ranked_optional = sorted(
        optional,
        key=lambda item: sha256(
            f"{seed}|dimension-pack|{item['code']}".encode()
        ).digest(),
    )
    selected_packs = [*mandatory, *ranked_optional[: max(0, len(seats) - 1)]]
    # Keep the legacy D7 reference on a deterministic, seed-dependent seat;
    # this branch is compatibility-only and does not constrain dynamic-v2.
    selected_packs.sort(
        key=lambda item: sha256(
            f"{seed}|dimension-pack|{item['code']}".encode()
        ).digest()
    )
    return {
        seat: dict(selected_packs[index])
        for index, seat in enumerate(ranked_seats)
    }


def _s3_s4_dimension_portfolios(
    seed: str,
    seat_keys: Sequence[str],
    *,
    dimensions_per_seat: int = 3,
) -> dict[str, dict[str, Any]]:
    """Build a multi-dimensional thinking portfolio for every S3/S4 seat.

    ``_s3_s4_dimension_assignments`` remains the compatibility surface for a
    seat's *primary* audit lane.  A primary lane is an orientation only,
    however; it must not turn a creative seat into a one-dimensional
    production line.  This helper adds a small, deterministic set of
    alternative winning dimensions to each seat.  The alternatives are
    selected by a stable hash, then repaired so that all seven dimensions are
    visible somewhere in the six-seat graph whenever capacity permits.

    The returned mapping deliberately keeps the original primary pack fields
    at the top level.  Existing callers can continue to read ``code``,
    ``label`` and ``focus`` while new callers use ``dimension_portfolio`` or
    ``alternate_dimensions`` to expose intra-seat divergence.
    """

    seats = [str(value) for value in seat_keys]
    if len(set(seats)) != len(seats):
        raise ValueError("seat_keys must be unique")
    if not seats:
        return {}
    # A creative seat must compare at least three distinct winning dimensions;
    # repair legacy/small caller hints upward instead of silently reducing the
    # exploration surface.
    bounded = max(3, min(int(dimensions_per_seat), len(S3_S4_WINNING_DIMENSION_PACKS)))
    primary = _s3_s4_dimension_assignments(seed, seats)
    packs_by_code = {
        str(item["code"]): dict(item) for item in S3_S4_WINNING_DIMENSION_PACKS
    }
    all_codes = [str(item["code"]) for item in S3_S4_WINNING_DIMENSION_PACKS]
    portfolios: dict[str, dict[str, Any]] = {}

    for seat in seats:
        primary_pack = dict(primary[seat])
        primary_code = str(primary_pack.get("code", ""))
        ranked_alternatives = sorted(
            (
                dict(item)
                for item in S3_S4_WINNING_DIMENSION_PACKS
                if str(item.get("code", "")) != primary_code
            ),
            key=lambda item: sha256(
                f"{seed}|dimension-portfolio|{seat}|{item['code']}".encode()
            ).digest(),
        )
        alternatives = ranked_alternatives[: max(0, bounded - 1)]
        portfolio = [
            {"role": "primary", **primary_pack},
            *[{"role": "alternate", **item} for item in alternatives],
        ]
        portfolios[seat] = {
            **primary_pack,
            "primary_dimension": dict(primary_pack),
            "alternate_dimensions": [dict(item) for item in alternatives],
            "dimension_portfolio": portfolio,
            "dimension_codes": [str(item.get("code", "")) for item in portfolio],
            "dimension_labels": [str(item.get("label", "")) for item in portfolio],
            "dimension_selection_rule": str(
                load_dynamic_winning_json(
                    "common", section="s3_s4.dimension_portfolio_metadata"
                ).get("closed_selection_rule", "")
            ),
        }

    # Six seats × three lenses normally provide 18 slots.  Ensure a dimension
    # that was not selected as a primary is still available to at least one
    # seat instead of being lost merely because the primary hash happened to
    # omit it.  Replace only an alternate slot, never the mandatory D7 or a
    # seat's primary lane.
    covered = {
        code
        for item in portfolios.values()
        for code in item.get("dimension_codes", [])
    }
    missing = [code for code in all_codes if code not in covered]
    for missing_code in missing:
        candidates = [
            seat
            for seat in seats
            if missing_code
            not in set(portfolios[seat].get("dimension_codes", []))
            and len(portfolios[seat].get("alternate_dimensions", [])) >= 1
        ]
        if not candidates:
            continue
        seat = min(
            candidates,
            key=lambda value: (
                len(portfolios[value].get("dimension_codes", [])),
                sha256(
                    f"{seed}|dimension-coverage|{value}|{missing_code}".encode()
                ).digest(),
            ),
        )
        replacement = dict(packs_by_code[missing_code])
        old = list(portfolios[seat]["alternate_dimensions"])
        # Replace the least stable alternate so replay remains deterministic.
        old[-1] = replacement
        portfolios[seat]["alternate_dimensions"] = old
        portfolios[seat]["dimension_portfolio"] = [
            {"role": "primary", **dict(portfolios[seat]["primary_dimension"])},
            *[{"role": "alternate", **dict(item)} for item in old],
        ]
        portfolios[seat]["dimension_codes"] = [
            str(item.get("code", ""))
            for item in portfolios[seat]["dimension_portfolio"]
        ]
        portfolios[seat]["dimension_labels"] = [
            str(item.get("label", ""))
            for item in portfolios[seat]["dimension_portfolio"]
        ]

    return portfolios


def _s3_s4_open_dimension_slots(
    seed: str,
    seat_keys: Sequence[str],
    *,
    dimension_hints: Mapping[str, Any] | Sequence[Any] | None = None,
    dimensions_per_seat: int = 3,
    mandatory_reference_code: str = "D7",
) -> dict[str, dict[str, Any]]:
    """Create exactly three *open* winning-dimension slots per creative seat.

    Dynamic-v2 used to call :func:`_s3_s4_dimension_assignments` and thereby
    turn the reviewed D1--D7 examples into a fixed production taxonomy.  That
    is useful for old checkpoints and audit fixtures, but it makes six creative
    seats converge on the same handful of labels before a model has read the
    Query.  This helper separates the durable capacity contract (three slots)
    from the dimension identity (model-authored at runtime).

    ``dimension_hints`` is intentionally permissive.  A selector may provide a
    mapping keyed by seat id, a list of rows carrying ``seat_id``/``seat_index``
    or a flat list shared by all seats.  Hints can name a reviewed D-code, an
    arbitrary ``OTHER`` relation, or only a battlefield relationship.  Every
    returned slot remains ``open=True`` and keeps the hint as an advisory seed;
    it is never a hard topic or a production quota.

    D7 is retained only as a mandatory *reference* on one deterministic slot.
    The slot's actual ``code`` remains an open slot id unless the model itself
    selected D7.  Consequently the source-forward idea is auditable without
    forcing every D7-referenced seat to author a source-strike weapon.
    """

    seats = [str(value) for value in seat_keys]
    if len(set(seats)) != len(seats):
        raise ValueError("seat_keys must be unique")
    if not seats:
        return {}
    try:
        bounded = max(3, int(dimensions_per_seat))
    except (TypeError, ValueError):
        bounded = 3
    # Keep the public contract at three slots.  The argument remains accepted
    # for callers that share policy values with the legacy portfolio helper.
    bounded = 3 if bounded != 3 else bounded

    def _text(value: Any) -> str:
        return str(value or "").strip()

    def _hint_row(value: Any, *, source: str = "model_dimension_hint") -> dict[str, Any] | None:
        if isinstance(value, Mapping):
            row = dict(value)
        elif _text(value):
            row = {"combat_dimension": _text(value)}
        else:
            return None
        # Nested dimension records are common in selector responses.
        nested = row.get("dimension")
        if isinstance(nested, Mapping):
            merged = dict(nested)
            merged.update({key: value for key, value in row.items() if key != "dimension"})
            row = merged
        code = _text(
            row.get("dimension_code")
            or row.get("code")
            or row.get("winning_dimension_code")
        )
        label = _text(
            row.get("combat_dimension")
            or row.get("label")
            or row.get("dimension_name")
            or row.get("dimension")
        )
        logic = _text(
            row.get("dimension_winning_logic")
            or row.get("winning_logic")
            or row.get("focus")
            or row.get("logic")
        )
        relationship = _text(
            row.get("battlefield_relationship")
            or row.get("changed_confrontation_variable")
            or row.get("relationship")
            or row.get("task_chain_breakpoint")
        )
        result = _text(
            row.get("desired_direct_result")
            or row.get("direct_military_result")
            or row.get("direct_military_effect")
        )
        if not any((code, label, logic, relationship, result)):
            return None
        # Do not copy arbitrary selector bookkeeping into the model-facing
        # slot.  Keep only semantic hint fields and a stable provenance tag.
        return {
            "code": code,
            "label": label,
            "winning_logic": logic,
            "battlefield_relationship": relationship,
            "desired_direct_result": result,
            "task_chain_breakpoint": _text(row.get("task_chain_breakpoint")),
            "engagement_geometry": _text(row.get("engagement_geometry")),
            "time_space_position": _text(row.get("time_space_position")),
            "forward_winning_question": _text(row.get("forward_winning_question")),
            "exclusion_boundary": _text(row.get("exclusion_boundary")),
            "source": _text(row.get("source")) or source,
            "open": True,
        }

    # Normalize both seat-specific and global hint shapes.  The dynamic
    # selector is allowed to evolve its JSON envelope without changing this
    # execution contract.
    by_seat: dict[str, list[dict[str, Any]]] = {seat: [] for seat in seats}
    global_hints: list[dict[str, Any]] = []

    def _append_for_seat(key: Any, values: Any) -> bool:
        token = _text(key)
        target: str | None = None
        if token in by_seat:
            target = token
        elif token.isdigit():
            index = int(token)
            if 0 <= index < len(seats):
                target = seats[index]
            elif 1 <= index <= len(seats):
                target = seats[index - 1]
        if target is None:
            return False
        rows = values if isinstance(values, list) else [values]
        for item in rows:
            # A nested ``dimensions``/``slots`` array is a seat envelope.
            if isinstance(item, Mapping) and isinstance(
                item.get("dimensions") or item.get("dimension_slots") or item.get("slots"),
                list,
            ):
                rows = list(
                    item.get("dimensions")
                    or item.get("dimension_slots")
                    or item.get("slots")
                )
                for nested in rows:
                    normalized = _hint_row(nested)
                    if normalized is not None:
                        by_seat[target].append(normalized)
                continue
            normalized = _hint_row(item)
            if normalized is not None:
                by_seat[target].append(normalized)
        return True

    if isinstance(dimension_hints, Mapping):
        # A single hint row is also a valid mapping input.  Distinguish it
        # from the seat-id -> rows envelope before iterating its fields.
        semantic_keys = {
            "code",
            "dimension_code",
            "winning_dimension_code",
            "label",
            "combat_dimension",
            "dimension_name",
            "winning_logic",
            "dimension_winning_logic",
            "battlefield_relationship",
            "changed_confrontation_variable",
            "relationship",
            "desired_direct_result",
            "direct_military_result",
            "direct_military_effect",
        }
        if semantic_keys.intersection(str(key) for key in dimension_hints):
            normalized = _hint_row(dimension_hints)
            if normalized is not None:
                global_hints.append(normalized)
        for key, values in dimension_hints.items():
            if not _append_for_seat(key, values):
                # A single envelope may itself contain a global dimensions
                # array.  It is handled below rather than discarded.
                if _text(key).casefold() in {
                    "dimensions",
                    "dimension_slots",
                    "slots",
                    "open_hints",
                    "hints",
                }:
                    values_list = values if isinstance(values, list) else [values]
                    for item in values_list:
                        normalized = _hint_row(item)
                        if normalized is not None:
                            global_hints.append(normalized)
                elif _text(key).casefold() in {"global", "shared", "all"}:
                    values_list = values if isinstance(values, list) else [values]
                    for item in values_list:
                        normalized = _hint_row(item)
                        if normalized is not None:
                            global_hints.append(normalized)
    elif isinstance(dimension_hints, Sequence) and not isinstance(
        dimension_hints, (str, bytes)
    ):
        for item in dimension_hints:
            if not isinstance(item, Mapping):
                normalized = _hint_row(item)
                if normalized is not None:
                    global_hints.append(normalized)
                continue
            target_key = (
                item.get("seat_id")
                or item.get("agent_instance_id")
                or item.get("producer_id")
                or item.get("seat_index")
            )
            nested = item.get("dimensions") or item.get("dimension_slots") or item.get("slots")
            if target_key is not None and nested is not None:
                if not _append_for_seat(target_key, nested):
                    for nested_item in nested if isinstance(nested, list) else [nested]:
                        normalized = _hint_row(nested_item)
                        if normalized is not None:
                            global_hints.append(normalized)
                continue
            if target_key is not None and _append_for_seat(target_key, item):
                continue
            normalized = _hint_row(item)
            if normalized is not None:
                global_hints.append(normalized)

    # De-duplicate hints by their *semantic dimension identity* while
    # retaining the first model ordering.  Different seats may intentionally
    # reuse a relationship; only a single seat's three slots must be distinct.
    # Using the full prose row here would let two descriptions of the same
    # ``D2``/``OTHER:<id>`` relation occupy multiple slots and would defeat
    # the per-seat three-dimension comparison contract.
    def _hint_key(row: Mapping[str, Any]) -> str:
        code = _text(row.get("code"))
        label = _text(row.get("label"))
        identity = _canonical_dimension_identity(code, fallback=label)
        if identity:
            return identity.casefold()
        # A row without an explicit code can still be a model-authored
        # dimension if it supplies a label or relationship.  Keep a compact
        # fallback identity so formatting-only differences do not create
        # duplicate slots.
        return "|".join(
            _text(row.get(key)).casefold()
            for key in (
                "label",
                "winning_logic",
                "battlefield_relationship",
                "desired_direct_result",
            )
        )

    def _unique(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            key = _hint_key(row)
            if not key or key in seen:
                continue
            seen.add(key)
            result.append(dict(row))
        return result

    global_hints = _unique(global_hints)
    for seat in seats:
        by_seat[seat] = _unique(by_seat[seat])

    # Pick one deterministic seat for the mandatory D7 reference.  This is
    # metadata for model exploration, not a primary dimension assignment.
    reference_seat = min(
        seats,
        key=lambda value: sha256(f"{seed}|open-dimension-reference|{value}".encode()).digest(),
    )
    packs_by_code = {
        _text(item.get("code")).upper(): dict(item)
        for item in S3_S4_WINNING_DIMENSION_PACKS
    }
    reference_pack = packs_by_code.get(_text(mandatory_reference_code).upper())
    portfolios: dict[str, dict[str, Any]] = {}
    for seat_index, seat in enumerate(seats):
        rows = list(by_seat.get(seat, []))
        # Global hints are distributed deterministically, preserving a seat's
        # own model-authored rows ahead of shared rows.
        if len(rows) < bounded and global_hints:
            offset = int.from_bytes(
                sha256(f"{seed}|open-dimension-hints|{seat}".encode()).digest()[:2],
                "big",
            ) % len(global_hints)
            for step in range(len(global_hints)):
                candidate = global_hints[(offset + step) % len(global_hints)]
                if _hint_key(candidate) not in {_hint_key(item) for item in rows}:
                    rows.append(dict(candidate))
                if len(rows) >= bounded:
                    break
        slots: list[dict[str, Any]] = []
        for slot_index in range(bounded):
            hint = dict(rows[slot_index]) if slot_index < len(rows) else {}
            explicit_code = _text(hint.get("code"))
            explicit_label = _text(hint.get("label"))
            digest = sha256(
                f"{seed}|open-dimension-slot|{seat}|{slot_index + 1}".encode()
            ).hexdigest()[:12]
            slot_code = explicit_code or f"OPEN-{digest}-{slot_index + 1}"
            metadata = load_dynamic_winning_json(
                "common", section="s3_s4.dimension_portfolio_metadata"
            )
            slot_label = explicit_label or str(
                metadata.get("open_slot_label_template", "")
            ).format(slot_index=slot_index + 1)
            slot = {
                "role": "open_slot",
                "slot_id": f"{seat}::open-dimension::{slot_index + 1}",
                "open": True,
                "code": slot_code,
                "label": slot_label,
                "winning_logic": _text(hint.get("winning_logic")),
                "task_chain_breakpoint": _text(hint.get("task_chain_breakpoint")),
                "battlefield_relationship": _text(hint.get("battlefield_relationship")),
                "engagement_geometry": _text(hint.get("engagement_geometry")),
                "time_space_position": _text(hint.get("time_space_position")),
                "desired_direct_result": _text(hint.get("desired_direct_result")),
                "forward_winning_question": _text(hint.get("forward_winning_question")),
                "exclusion_boundary": _text(hint.get("exclusion_boundary")),
                "hint_source": _text(hint.get("source")) or "open_slot_fallback",
                "reference_code": "",
                "reference_label": "",
            }
            if seat == reference_seat and slot_index == 0:
                slot["reference_code"] = _text(mandatory_reference_code).upper()
                slot["reference_label"] = _text(
                    (reference_pack or {}).get("label")
                ) or "源头前出"
                slot["reference_only"] = True
                # Keep the D7 pack's explanatory fields as optional inspiration
                # only when the model did not provide a relationship of its own.
                if reference_pack:
                    for key in (
                        "task_chain_breakpoint",
                        "battlefield_relationship",
                        "engagement_geometry",
                        "time_space_position",
                        "desired_direct_result",
                        "forward_winning_question",
                        "exclusion_boundary",
                    ):
                        if not _text(slot.get(key)):
                            slot[key] = _text(reference_pack.get(key))
                    if not _text(slot.get("winning_logic")):
                        slot["winning_logic"] = _text(reference_pack.get("focus"))
            slots.append(slot)

        primary = dict(slots[0])
        portfolios[seat] = {
            "open": True,
            "slot_count": bounded,
            "primary_dimension": primary,
            # These aliases keep downstream handoff code stable while making
            # clear that the primary is only an opening lens.
            "primary_dimension_code": _text(primary.get("code")),
            "primary_dimension_label": _text(primary.get("label")),
            "alternate_dimensions": [dict(item) for item in slots[1:]],
            "dimension_portfolio": slots,
            "dimension_codes": [_text(item.get("code")) for item in slots],
            "dimension_labels": [_text(item.get("label")) for item in slots],
            "reference_dimension_codes": sorted(
                {
                    _text(item.get("reference_code"))
                    for item in slots
                    if _text(item.get("reference_code"))
                }
            ),
            # Explicit alias for consumers that must distinguish a
            # reference-only hint from a hard production dimension.  Keep the
            # historical ``reference_dimension_codes`` field above for
            # checkpoint/UI compatibility.
            "reference_only_dimension_codes": sorted(
                {
                    _text(item.get("reference_code"))
                    for item in slots
                    if _text(item.get("reference_code"))
                }
            ),
            "dimension_selection_rule": str(
                load_dynamic_winning_json(
                    "common", section="s3_s4.dimension_portfolio_metadata"
                ).get("open_selection_rule", "")
            ),
        }
    return portfolios


def _s3_s4_dimension_pack_for(value: Any) -> dict[str, str] | None:
    """Resolve a model-authored dimension code or label to its pack."""

    token = str(value or "").strip().casefold()
    if not token:
        return None
    for item in S3_S4_WINNING_DIMENSION_PACKS:
        if token in {
            str(item.get("code", "")).casefold(),
            str(item.get("label", "")).casefold(),
        }:
            return dict(item)
    return None


def _dimension_marker_text(value: Any) -> str:
    """Return a compact, Unicode-normalized authored dimension token.

    Providers occasionally prefix a dimension with ``dimension:`` while
    others return the human label directly.  Keeping this cleanup in one
    place lets resolver and S5 use exactly the same identity rules without
    inspecting equipment names or inferring a combat lane from free prose.
    """

    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    return re.sub(r"^dimension\s*[:：]?\s*", "", text, flags=re.IGNORECASE)


def _dimension_slug(value: Any) -> str:
    """Build a stable comparison slug for a model-authored dimension."""

    text = _dimension_marker_text(value).casefold()
    text = re.sub(r"\s+", "", text)
    return re.sub(r"[^a-z0-9\u3400-\u9fff]+", "", text)


def _other_dimension_suffix(value: Any) -> str | None:
    """Return the suffix for an explicit ``OTHER`` token.

    ``None`` means the token is not an OTHER marker; an empty string means a
    bare ``OTHER`` marker.  Requiring a separator avoids treating words such
    as ``otherwise`` as a dimension marker.
    """

    token = _dimension_marker_text(value)
    if not token:
        return None
    match = re.match(
        r"^other(?:$|\s+|\s*[:：\-|—/／_]\s*)(.*)$",
        token,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    return str(match.group(1) or "").strip()


def _canonical_dimension_identity(
    value: Any,
    *,
    fallback: Any = "",
) -> str:
    """Canonicalize a dimension for S5 grouping.

    Built-in D-codes and labels retain their reviewed identity.  Explicit
    ``OTHER:<id>`` values retain the stable custom suffix; a bare ``OTHER``
    can be disambiguated by a richer authored label.  Other model-authored
    short IDs are preserved as opaque tokens (normalised only for comparison).
    """

    packs_by_code = {
        str(pack.get("code", "")).strip().upper(): pack
        for pack in S3_S4_WINNING_DIMENSION_PACKS
        if str(pack.get("code", "")).strip()
    }
    labels_by_token = {
        unicodedata.normalize("NFKC", str(pack.get("label", "")))
        .strip()
        .casefold(): code
        for code, pack in packs_by_code.items()
        if str(pack.get("label", "")).strip()
    }

    token = _dimension_marker_text(value)
    if not token:
        return _canonical_dimension_identity(fallback) if str(fallback or "").strip() else ""

    # An explicit OTHER marker denotes a model-authored relation even when
    # its suffix contains a reviewed label. Resolve it before D-code/label
    # matching so custom relations cannot be silently folded into D1--D7.
    other_suffix = _other_dimension_suffix(token)
    if other_suffix is not None:
        suffix = _dimension_slug(other_suffix)
        if not suffix and str(fallback or "").strip():
            fallback_token = _dimension_marker_text(fallback)
            fallback_suffix = _other_dimension_suffix(fallback_token)
            if fallback_suffix is not None:
                suffix = _dimension_slug(fallback_suffix)
            elif fallback_token.casefold() != "other":
                suffix = _dimension_slug(fallback_token)
        return f"other:{suffix}" if suffix else "other"

    # A reviewed D-code is accepted only when it is the token's leading
    # marker.  Do not reclassify an opaque custom id such as ``X-D1`` merely
    # because it happens to contain the characters ``D1``.
    code_match = re.match(
        r"^D\s*([1-7])(?:$|[^A-Za-z0-9])",
        token.upper(),
    )
    if code_match:
        code = f"D{code_match.group(1)}"
        if code in packs_by_code:
            return code.casefold()

    compact = re.sub(r"\s+", "", token).casefold()
    if compact in {code.casefold() for code in packs_by_code}:
        return compact
    if compact in labels_by_token:
        return labels_by_token[compact].casefold()
    for label_token, code in labels_by_token.items():
        if label_token and (compact.startswith(label_token) or label_token in compact):
            return code.casefold()

    return re.sub(r"[^a-z0-9\u3400-\u9fff]+", "", compact)


def _stable_authored_dimension_code(
    value: Any,
    *,
    fallback_label: Any = "",
) -> str:
    """Return the resolver's stable, model-authored dimension code.

    The display form intentionally keeps custom short IDs intact.  Only the
    ``OTHER`` family is rewritten to a canonical ``OTHER:<slug>`` form so a
    generic ``dimension_code=OTHER`` cannot merge unrelated authored
    relations in S5.
    """

    token = _dimension_marker_text(value)
    if not token:
        token = _dimension_marker_text(fallback_label)
    if not token:
        return ""
    pack = _s3_s4_dimension_pack_for(token)
    if pack is not None:
        return str(pack.get("code", "")).strip()
    canonical = _canonical_dimension_identity(token, fallback=fallback_label)
    if canonical.startswith("other:"):
        return f"OTHER:{canonical.split(':', 1)[1]}"
    if canonical == "other":
        # A bare OTHER with a richer label is disambiguated by the canonical
        # helper; retain the generic marker only when no label exists.
        label_slug = _dimension_slug(fallback_label)
        if label_slug and label_slug != "other":
            return f"OTHER:{label_slug}"
        return "OTHER"
    # Preserve a custom short ID's authored spelling (apart from surrounding
    # whitespace and the optional ``dimension:`` prefix).  S5 normalises it
    # separately for stable grouping.
    return re.sub(r"\s+", " ", token).strip()


def _s3_s4_dimension_catalog(
    assignment: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Return the compact dimension matrix handed to one creator seat."""

    raw = assignment or {}
    portfolio = raw.get("dimension_portfolio", [])
    if not isinstance(portfolio, list):
        portfolio = []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in portfolio:
        if not isinstance(item, Mapping):
            continue
        code = str(item.get("code", "")).strip()
        pack = _s3_s4_dimension_pack_for(code) or _s3_s4_dimension_pack_for(
            item.get("label", "")
        )
        # Open slots may carry a model-authored label/relationship that is not
        # present in the reviewed D1--D7 hint catalog.  Preserve those rows
        # rather than silently reducing the creator to a one-dimensional (or
        # empty) prompt.  Built-in packs are still enriched with their full
        # explanatory fields for compatibility.
        if pack is None:
            custom_code = code or "OTHER"
            custom_key = custom_code.casefold()
            if custom_key in seen:
                continue
            seen.add(custom_key)
            rows.append(
                {
                    "code": custom_code,
                    "label": str(item.get("label", "") or custom_code).strip(),
                    "winning_logic": str(
                        item.get("winning_logic")
                        or item.get("dimension_winning_logic", "")
                    ).strip(),
                    "task_chain_breakpoint": str(
                        item.get("task_chain_breakpoint", "")
                    ).strip(),
                    "battlefield_relationship": str(
                        item.get("battlefield_relationship", "")
                    ).strip(),
                    "engagement_geometry": str(
                        item.get("engagement_geometry", "")
                    ).strip(),
                    "time_space_position": str(
                        item.get("time_space_position", "")
                    ).strip(),
                    "desired_direct_result": str(
                        item.get("desired_direct_result", "")
                    ).strip(),
                    "forward_winning_question": str(
                        item.get("forward_winning_question", "")
                    ).strip(),
                    "exclusion_boundary": str(
                        item.get("exclusion_boundary", "")
                    ).strip(),
                    "open": bool(item.get("open", True)),
                    "slot_id": str(item.get("slot_id", "")).strip(),
                    "reference_code": str(item.get("reference_code", "")).strip(),
                    "reference_label": str(item.get("reference_label", "")).strip(),
                    "reference_only": bool(item.get("reference_only", False)),
                }
            )
            continue
        if pack["code"] in seen:
            continue
        seen.add(pack["code"])
        rows.append(
            {
                "code": pack["code"],
                "label": pack["label"],
                "winning_logic": pack["focus"],
                "task_chain_breakpoint": pack["task_chain_breakpoint"],
                "battlefield_relationship": pack["battlefield_relationship"],
                "engagement_geometry": pack["engagement_geometry"],
                "time_space_position": pack["time_space_position"],
                "desired_direct_result": pack["desired_direct_result"],
                "forward_winning_question": pack["forward_winning_question"],
                "exclusion_boundary": pack["exclusion_boundary"],
            }
        )
    # Compatibility fallback for assignments persisted before the portfolio
    # field was introduced.
    if not rows:
        pack = _s3_s4_dimension_pack_for(
            raw.get("dimension_code") or raw.get("combat_dimension")
        )
        if pack is not None:
            rows.append(
                {
                    "code": pack["code"],
                    "label": pack["label"],
                    "winning_logic": pack["focus"],
                    "task_chain_breakpoint": pack["task_chain_breakpoint"],
                    "battlefield_relationship": pack["battlefield_relationship"],
                    "engagement_geometry": pack["engagement_geometry"],
                    "time_space_position": pack["time_space_position"],
                    "desired_direct_result": pack["desired_direct_result"],
                    "forward_winning_question": pack["forward_winning_question"],
                    "exclusion_boundary": pack["exclusion_boundary"],
                }
            )
    return rows


def _s5_dimension_key(item: Any) -> str:
    """Return the explicit S3/S4 winning dimension used for portfolio focus.

    A dimension is deliberately taken from authored assignment metadata, never
    inferred from equipment names or Chinese keywords.  Empty legacy rows get
    a private per-candidate key so old runs retain score-only ordering.
    """

    def field(value: Any, name: str) -> Any:
        if isinstance(value, Mapping):
            return value.get(name, "")
        return getattr(value, name, "")

    def is_transport_marker(value: Any) -> bool:
        """Recognize controller slot markers, which are not dimensions."""

        token = _dimension_marker_text(value)
        if not token:
            return False
        marker = token.casefold().replace(" ", "")
        if "::open-dimension::" in marker:
            return True
        return marker in {
            "open",
            "open_slot",
            "open-slot",
            "auto",
            "dynamic",
            "dynamic-open",
            "dynamic_open",
            "dynamicopen",
            "query开放制胜维度",
            # Resolver fallback when no authored dimension survives.  This is
            # a transport placeholder, not a model-authored competition lane.
            "primary",
        } or marker.startswith("query开放制胜槽位") or bool(
            re.match(r"^query开放制胜(?:槽位|维度)\d*$", marker)
        ) or bool(
            re.match(
                r"^open(?:[_-]?slot)?[-_:][a-z0-9]{4,}(?:[-_:][a-z0-9]+)*$",
                marker,
            )
        )

    # Prefer an explicit authored code, but do not let a generic ``OTHER``
    # marker hide a richer combat-dimension label.  This is the key guard
    # against merging unrelated model-authored OTHER relations into one S5
    # competition lane.  Resolver-generated angle ids carry the canonical
    # custom suffix, so recover that suffix when the dataclass has no separate
    # ``dimension_code`` field.
    raw_code = field(item, "dimension_code")
    raw_label = field(item, "combat_dimension")
    # ``WinningHypothesis`` historically has no separate dimension_code
    # field, so resolver-generated angle ids are the durable place where a
    # model-authored stable code can survive.  Ignore OPEN/AUTO transport
    # markers before using either code or label for S5 competition.
    usable_code = "" if is_transport_marker(raw_code) else str(raw_code or "").strip()
    usable_label = "" if is_transport_marker(raw_label) else str(raw_label or "").strip()
    dimension = _canonical_dimension_identity(usable_code, fallback=usable_label)
    angle = str(field(item, "winning_angle_id") or "").strip()
    angle_suffix = angle.rsplit("::", 1)[-1] if angle else ""
    angle_dimension = (
        ""
        if is_transport_marker(angle) or is_transport_marker(angle_suffix)
        else _canonical_dimension_identity(angle_suffix)
        if angle
        else ""
    )
    # Prefer the explicit suffix from a resolver-generated ``assignment::id``
    # angle when no standalone code was persisted.  This keeps one authored
    # custom code in a single S5 lane even when its human-readable labels vary
    # between candidates.
    if angle_dimension and "::" in angle and not usable_code:
        dimension = angle_dimension
    if (
        angle_dimension.startswith("other:")
        and (
            not usable_code
            or _canonical_dimension_identity(usable_code) == "other"
        )
    ):
        dimension = angle_dimension
    if dimension:
        return f"dimension:{dimension}"
    if angle and not is_transport_marker(angle) and not is_transport_marker(angle_suffix):
        # An angle id often embeds the explicit dimension (for example
        # ``query-winning-angle-2::D3``).  Use that code when present; retain
        # the full opaque id for genuinely model-authored OTHER angles.
        angle_dimension = (
            ""
            if is_transport_marker(angle_suffix)
            else _canonical_dimension_identity(angle_suffix)
        )
        if angle_dimension:
            return f"dimension:{angle_dimension}"
        normalized_angle = re.sub(
            r"[^a-z0-9\u3400-\u9fff]+",
            "",
            unicodedata.normalize("NFKC", angle).casefold(),
        )
        return f"angle:{normalized_angle}"
    hypothesis_id = str(field(item, "hypothesis_id") or "").strip()
    return f"candidate:{hypothesis_id}"


def _s3_s4_resolve_authored_dimension(
    raw: Mapping[str, Any],
    *,
    sidecar: Mapping[str, Any] | None,
    assignment: Mapping[str, Any],
) -> dict[str, str]:
    """Resolve a creator's optional dimension sidecar without forcing it.

    The compact creator schema historically contained only ``name`` and
    ``concise_winning_summary``.  Newer providers may return a sidecar or
    inline dimension fields.  This resolver accepts both forms and falls back
    to the seat's primary lane only when the model supplied no usable choice.
    """

    sidecar = sidecar if isinstance(sidecar, Mapping) else {}
    raw_code = str(raw.get("dimension_code") or "").strip()
    raw_label = str(raw.get("combat_dimension") or "").strip()
    sidecar_code = str(sidecar.get("dimension_code") or "").strip()
    sidecar_label = str(sidecar.get("combat_dimension") or "").strip()

    def _is_open_marker(value: Any) -> bool:
        token = _dimension_marker_text(value).casefold().replace(" ", "")
        if token in {
            "open",
            "open_slot",
            "open-slot",
            "auto",
            "dynamic",
            "dynamic-open",
            "dynamic_open",
            "dynamicopen",
            "query开放制胜维度".casefold(),
        }:
            return True
        if token.startswith("query开放制胜槽位"):
            return True
        if re.match(r"^query开放制胜(?:槽位|维度)\d*$", token):
            return True
        # Controller-generated slots use ``OPEN-<digest>-<ordinal>``.  Treat
        # that reserved namespace as a marker too; otherwise a model echoing
        # the slot id would be mistaken for a self-authored dimension.
        return bool(
            re.match(
                r"^open(?:[_-]?slot)?[-_:][a-z0-9]{4,}(?:[-_:][a-z0-9]+)*$",
                token,
            )
        )

    # ``OPEN``/``AUTO`` are controller slot markers, not authored winning
    # dimensions.  Keep an explicit code ahead of a display label—even when
    # that code is the generic ``OTHER`` marker—so a paired label can be used
    # to derive a stable ``OTHER:<short-id>`` rather than losing its identity.
    code_values = [
        value
        for value in (raw_code, sidecar_code)
        if value and not _is_open_marker(value)
    ]
    label_values = [
        value
        for value in (raw_label, sidecar_label)
        if value and not _is_open_marker(value)
    ]
    specific_code_values = [
        value
        for value in code_values
        if not (
            _other_dimension_suffix(value) == ""
            and _dimension_marker_text(value).casefold() == "other"
        )
    ]
    authored_code = (specific_code_values or code_values or label_values or [""])[0]
    authored_logic = str(
        raw.get("dimension_winning_logic")
        or sidecar.get("dimension_winning_logic")
        or ""
    ).strip()
    authored_angle = str(
        raw.get("winning_angle_id")
        or sidecar.get("winning_angle_id")
        or ""
    ).strip()
    authored_label = next(
        (
            value
            for value in (raw_label, sidecar_label)
            if value and not _is_open_marker(value)
        ),
        "",
    )
    pack = _s3_s4_dimension_pack_for(authored_code)
    if pack is not None:
        code = pack["code"]
        # An explicit reviewed code is authoritative.  Do not let an
        # inconsistent display label move a D1--D7 candidate into a custom
        # S5 lane merely because the dataclass stores ``combat_dimension``.
        combat_dimension = authored_code
        if authored_code.casefold() == code.casefold():
            combat_dimension = code
        return {
            "winning_angle_id": authored_angle
            or f"{assignment.get('assignment_id', 'seat-angle')}::{code}",
            "combat_dimension": combat_dimension,
            "dimension_winning_logic": authored_logic or pack["focus"],
            "dimension_code": code,
        }
    if authored_code:
        # Preserve a genuinely model-authored OTHER relation.  Do not turn an
        # arbitrary phrase into a built-in D1-D7 lane by lexical guessing.
        stable_code = _stable_authored_dimension_code(
            authored_code,
            fallback_label=authored_label,
        ) or "OTHER"
        bare_other_code = (
            _other_dimension_suffix(authored_code) == ""
            and _dimension_marker_text(authored_code).casefold() == "other"
        )
        display_dimension = (
            stable_code if bare_other_code else (authored_label or authored_code)
        )
        return {
            "winning_angle_id": authored_angle
            or f"{assignment.get('assignment_id', 'seat-angle')}::{stable_code}",
            "combat_dimension": display_dimension,
            "dimension_winning_logic": authored_logic,
            "dimension_code": stable_code,
        }
    fallback_code = str(
        assignment.get("primary_dimension_code")
        or assignment.get("dimension_code", "")
    ).strip()
    fallback_label = str(
        assignment.get("primary_dimension_label")
        or assignment.get("combat_dimension", "")
    ).strip()
    fallback_pack = _s3_s4_dimension_pack_for(fallback_code or fallback_label)
    if fallback_pack is not None:
        fallback_code = fallback_pack["code"]
        fallback_label = fallback_pack["label"]
        authored_logic = authored_logic or fallback_pack["focus"]
    return {
        "winning_angle_id": authored_angle
        or f"{assignment.get('assignment_id', 'seat-angle')}::{fallback_code or 'PRIMARY'}",
        "combat_dimension": fallback_label or fallback_code,
        "dimension_winning_logic": authored_logic,
        "dimension_code": fallback_code,
    }


def _s5_merge_target_is_valid(
    source_hypothesis_id: Any,
    target_hypothesis_id: Any,
    known_hypothesis_ids: set[str],
    candidate_scope: set[str] | None = None,
) -> bool:
    """Validate an S5 merge target before mutating the candidate ledger.

    A merge is a scoped judgement, not a free-form alias assignment.  The
    target must name a currently live candidate, must not be the source itself,
    and (for paired dynamic reviewers) must belong to that reviewer's declared
    candidate slice.  Keeping this check pure makes malformed provider output
    easy to test and prevents an invalid merge from inheriting the caller's
    default-retain state.
    """

    source_id = str(source_hypothesis_id or "").strip()
    target_id = str(target_hypothesis_id or "").strip()
    known_ids = {str(value).strip() for value in known_hypothesis_ids if str(value).strip()}
    scope_ids = {
        str(value).strip() for value in (candidate_scope or set()) if str(value).strip()
    }
    return bool(
        target_id
        and target_id in known_ids
        and target_id != source_id
        and (not scope_ids or target_id in scope_ids)
    )


def _s5_diverse_portfolio_order(
    candidates: Sequence[Any],
    *,
    weighted_scores: Mapping[str, float] | None = None,
    innovation_priorities: Mapping[str, float] | None = None,
    disruption_tiers: Mapping[str, str] | None = None,
    portfolio_order_hints: Mapping[str, int] | None = None,
    maximum: int = 7,
) -> tuple[list[Any], dict[str, Any]]:
    """Select one strongest candidate per explicit combat dimension.

    The first pass resolves competition *inside* each dimension.  Only those
    winners then compete across dimensions by the S5 weighted score; this
    prevents a high-scoring cluster of near-identical ideas from consuming all
    finalist slots.  Rows without assignment metadata remain independent keys,
    preserving backward compatibility for historical ledgers.
    """

    score_map = weighted_scores or {}
    priority_map = innovation_priorities or {}
    tier_map = disruption_tiers or {}
    hint_map = portfolio_order_hints or {}
    # ``maximum`` is caller-configurable for compatibility, but dynamic S5's
    # contract has a hard seven-card ceiling.  Enforce it here as well so a
    # future caller cannot accidentally bypass the portfolio bound.
    limit = max(1, min(7, int(maximum)))

    def candidate_field(item: Any, name: str, default: Any = "") -> Any:
        if isinstance(item, Mapping):
            return item.get(name, default)
        return getattr(item, name, default)

    def rank(item: Any) -> tuple[float, int, float, int, float, str]:
        hypothesis_id = str(candidate_field(item, "hypothesis_id") or "")
        try:
            score = float(
                score_map.get(
                    hypothesis_id,
                    candidate_field(item, "score", 0.0),
                )
                or 0.0
            )
        except (TypeError, ValueError):
            score = 0.0
        try:
            priority = float(priority_map.get(hypothesis_id, 0.0) or 0.0)
        except (TypeError, ValueError):
            priority = 0.0
        tier = _s5_disruption_tier_rank(tier_map.get(hypothesis_id), priority)
        try:
            base_score = float(candidate_field(item, "score", 0.0) or 0.0)
        except (TypeError, ValueError):
            base_score = 0.0
        return (
            score,
            tier,
            priority,
            -int(hint_map.get(hypothesis_id, 10**9)),
            base_score,
            hypothesis_id,
        )

    groups: dict[str, list[Any]] = {}
    # Candidates with no authored dimension are historical/partial rows.  Do
    # not turn each candidate id into a synthetic competition lane: doing so
    # lets a large batch of dimension-less rows crowd out independent,
    # explicitly declared combat dimensions before the seven-card cap is
    # applied.  They are collected separately and considered only after all
    # explicit dimension winners have competed.
    legacy_rows: list[Any] = []
    for item in candidates:
        hypothesis_id = str(candidate_field(item, "hypothesis_id") or "")
        if not hypothesis_id:
            continue
        dimension_key = _s5_dimension_key(item)
        if dimension_key.startswith("candidate:"):
            legacy_rows.append(item)
            continue
        groups.setdefault(dimension_key, []).append(item)

    winners: list[Any] = []
    competition: dict[str, list[str]] = {}
    winner_by_dimension: dict[str, str] = {}
    for dimension_key, rows in groups.items():
        ordered = sorted(rows, key=rank, reverse=True)
        winner = ordered[0]
        winners.append(winner)
        winner_by_dimension[dimension_key] = str(
            candidate_field(winner, "hypothesis_id")
        )
        competition[dimension_key] = [
            str(candidate_field(row, "hypothesis_id")) for row in ordered
        ]
    winners.sort(key=rank, reverse=True)
    selected = winners[:limit]
    selected_ids = {
        str(candidate_field(item, "hypothesis_id")) for item in selected
    }
    # If independent dimensions do not fill the requested cap, only legacy
    # rows with no explicit dimension metadata may be used as overflow. An
    # explicit dimension is a competition lane: its runner-up remains a
    # reference/merge candidate, never a second finalist that crowds out a
    # different lane. This is the concrete implementation of
    # “同一维度只取最优、跨维度优先覆盖”.
    # Dimension-less legacy rows are strictly a final backfill.  Explicit
    # dimension runner-ups never enter this list, even if they score higher.
    backups = sorted(
        [
            item
            for item in legacy_rows
            if str(candidate_field(item, "hypothesis_id")) not in selected_ids
        ],
        key=rank,
        reverse=True,
    )
    selected_backup_ids: list[str] = []
    for item in backups:
        if len(selected) >= limit:
            break
        selected.append(item)
        candidate_id = str(candidate_field(item, "hypothesis_id"))
        selected_ids.add(candidate_id)
        selected_backup_ids.append(candidate_id)
    return selected, {
        "dimension_groups": competition,
        "dimension_winner_ids": winner_by_dimension,
        "legacy_candidate_ids": [
            str(candidate_field(item, "hypothesis_id")) for item in legacy_rows
        ],
        "selected_backup_ids": selected_backup_ids,
        "selection_rule": "dimension_winners_first_then_weighted_score_backfill",
    }


def _random_s3_s4_naming_types(seed: str, *, count: int = 2) -> list[dict[str, str]]:
    """Return a reproducible random-style sample for one creative call.

    S3/S4 calls can be resumed from checkpoints.  A hash-ranked sample gives
    each run, Agent seat and creative iteration a varied A–O assignment while
    keeping the assignment stable when that exact call is replayed.
    """

    bounded_count = max(1, min(int(count), len(S3_S4_WEAPON_NAMING_TYPES)))
    ranked = sorted(
        S3_S4_WEAPON_NAMING_TYPES,
        key=lambda item: sha256(
            f"{seed}|{item['code']}|新质武器装备命名".encode("utf-8")
        ).digest(),
    )
    return [dict(item) for item in ranked[:bounded_count]]


def _s3_s4_naming_assignment(seed: str, *, count: int = 2) -> dict[str, Any]:
    naming_types = _random_s3_s4_naming_types(seed, count=count)
    metadata = load_dynamic_winning_json(
        "common", section="s3_s4.naming_assignment_metadata"
    )
    return {
        "source": "新质武器装备命名类型体系.md（A—O）",
        "selection_mode": "random_without_replacement",
        "candidate_order": [
            {"candidate_position": position, **naming_type}
            for position, naming_type in enumerate(naming_types, start=1)
        ],
        "name_length": str(metadata.get("name_length", "")),
        "application_rule": str(metadata.get("application_rule", "")),
    }


def _targeted_expert_feedback(
    feedback: Any,
    agent_ref: str | int,
) -> list[dict[str, Any]]:
    """Keep only review signals explicitly addressed to this S-agent.

    Feedback is shared at run level so the audit trail can preserve the full
    review.  Prompt handoffs, however, should not make an S3-only note steer
    S6 (or vice versa); normalize both catalog ids (``S3``) and runtime agent
    names (``winning_s3_breakthrough``) to the same stage reference.
    """

    if not isinstance(feedback, (list, tuple)):
        return []
    match = re.search(r"(?:^|[^0-9])S?([1-6])(?:[^0-9]|$)", str(agent_ref).upper())
    target = f"S{match.group(1)}" if match else str(agent_ref).upper().strip()
    selected: list[dict[str, Any]] = []
    for item in feedback:
        if not isinstance(item, Mapping):
            continue
        raw_targets = item.get("target_agent_ids")
        targets = {
            str(value).upper().strip()
            for value in (
                raw_targets if isinstance(raw_targets, (list, tuple)) else [raw_targets]
            )
            if str(value).strip()
        }
        # Older records without target metadata remain usable by every quality
        # stage; newly normalized records always carry explicit targets.
        if not targets or target in targets:
            selected.append(dict(item))
    return selected


def _open_s3_exploration_brief(
    topic: str,
    structured_query_brief: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Give early winning Agents the problem boundary, not blueprint answers.

    The discovery blueprint may contain useful downstream planning hypotheses,
    but fields that already resemble weapon architectures, enabling solutions
    or project theses strongly anchor an otherwise isolated Codex session.  The
    creative S3/S4 producers therefore receive the Query-derived combat problem
    and controller blueprint. S5 receives only the Query plus each candidate's
    routed id, name and concise winning summary.
    """

    full = _query_combat_equipment_divergence_brief(
        topic,
        structured_query_brief=structured_query_brief or {},
    )
    boundary_keys = (
        "query",
        "combat_problem_frame",
        "enemy_target_profile",
        "battle_phase_and_constraints",
        "required_direct_military_effects",
        "equipment_semantic_boundary",
        "winning_problem_propositions",
    )
    return {
        **{
            key: full.get(key, [] if key.endswith("s") else "") for key in boundary_keys
        },
        "generation_rules": [
            item.strip(" -*")
            for item in load_dynamic_winning_prompt(
                "common", section="s3_s4.generation_rules"
            ).splitlines()
            if item.strip(" -*")
        ],
        "solution_hypotheses_withheld": True,
    }


def _open_s3_theme_contract() -> dict[str, Any]:
    """Keep shared examples and fixed lenses out of creative generation."""

    return {
        "authority": load_dynamic_winning_prompt(
            "common", section="s3_s4.theme_authority"
        ),
        "candidate_boundary": load_dynamic_winning_prompt(
            "common", section="s3_s4.theme_candidate_boundary"
        ),
        "creative_freedom": load_dynamic_winning_prompt(
            "common", section="s3_s4.theme_creative_freedom"
        ),
        "template_guard": load_dynamic_winning_prompt(
            "common", section="s3_s4.theme_template_guard"
        ),
        "examples_withheld": True,
    }


def _open_s3_theme_instruction() -> str:
    return load_dynamic_winning_prompt("common", section="s3_s4.theme_instruction")


def _creative_s3_candidate_instruction() -> str:
    """Give S3/S4 a small creative contract and leave the invention to Codex."""

    return load_dynamic_winning_prompt("common", section="s3_s4.creative_contract")


def _s3_s4_quality_first_instruction() -> str:
    """Force a small, quality-first handoff from each creative session."""

    return load_dynamic_winning_prompt("common", section="s3_s4.quality_first")


def _s3_s4_rows_need_creative_retry(rows: Sequence[Any]) -> bool:
    """Detect only obvious authoring failure, leaving invention to Codex.

    This intentionally avoids local novelty keywords, name templates and
    equipment-type quotas.  A retry is warranted when a draft is empty,
    mechanically opened, too short to state a causal win, or lacks a
    sentence boundary.  Whether the idea is genuinely disruptive remains a
    model-owned S5 judgement.
    """

    if not rows:
        return True
    for row in rows:
        if not isinstance(row, Mapping):
            return True
        name = str(row.get("name") or row.get("title") or "").strip()
        summary = str(row.get("concise_winning_summary", "") or "").strip()
        if not name or not summary:
            return True
        if _s3_s4_name_authoring_issues(name):
            return True
        issues = set(winning_summary_language_issues(summary))
        if {
            "winning_summary_missing",
            "winning_summary_mechanical_opening",
            "winning_summary_too_short",
            "winning_summary_incomplete_sentence",
        } & issues:
            return True
    return False


def _s3_s4_name_authoring_issues(name: Any) -> list[str]:
    """Flag only unmistakable placeholder/non-final equipment names.

    This is a narrow authoring gate, not a novelty or naming-style scorer.  It
    exists to send an obviously unfinished name back to an isolated Codex
    creator; it never rewrites a name locally and does not reject an unusual
    but explainable model-authored designation.
    """

    normalized = re.sub(r"\s+", "", str(name or "")).strip().lower()
    if not normalized:
        return ["name_missing"]
    markers = (
        "占位符",
        "占位",
        "待定",
        "未命名",
        "示例",
        "测试",
        "placeholder",
        "todo",
        "tbd",
        "dummy",
        "example",
        "testname",
    )
    return (
        ["placeholder_or_nonfinal_marker"]
        if any(marker in normalized for marker in markers)
        else []
    )


def _bounded_semantic_review_window(
    candidates: Sequence[WinningHypothesis],
    *,
    changed_hypothesis_ids: set[str] | None = None,
    maximum_candidates: int = 14,
) -> tuple[list[WinningHypothesis], list[list[str]]]:
    """Select a bounded semantic-review slice without mutating the ledger."""

    if len(candidates) > maximum_candidates:
        review_candidates = sorted(
            candidates,
            key=lambda item: (
                item.hypothesis_id not in (changed_hypothesis_ids or set()),
                -item.score,
                -len(item.evidence_ids),
                item.hypothesis_id,
            ),
        )[:maximum_candidates]
    else:
        review_candidates = list(candidates)
    pair_ids = [
        [left.hypothesis_id, right.hypothesis_id]
        for index, left in enumerate(review_candidates)
        for right in review_candidates[index + 1 :]
        if not changed_hypothesis_ids
        or left.hypothesis_id in changed_hypothesis_ids
        or right.hypothesis_id in changed_hypothesis_ids
    ]
    return review_candidates, pair_ids


def _minimal_s6_card_handoff(brief: Mapping[str, Any]) -> dict[str, Any]:
    """Project one frozen S5 decision spine into a small, per-card S6 handoff."""

    def compact(value: Any, limit: int = 360) -> Any:
        if isinstance(value, str):
            text = " ".join(value.split()).strip()
            if len(text) <= limit:
                return text
            candidate = text[:limit]
            boundary = max(candidate.rfind(mark) for mark in "。！？；")
            return candidate[: boundary + 1] if boundary >= limit // 2 else candidate
        if isinstance(value, Mapping):
            return {
                str(k): compact(v, 180)
                for k, v in list(value.items())[:8]
                if v not in (None, "", [], {})
            }
        if isinstance(value, (list, tuple)):
            return [
                compact(v, 180) for v in list(value)[:4] if v not in (None, "", [], {})
            ]
        return value

    fields = (
        "hypothesis_id",
        "name",
        "primary_equipment_identity",
        "equipment_form",
        "unique_operational_role",
        "target_and_direct_effect",
        "non_substitutable_difference",
        "query_relevance",
        "indicator_portrait",
        "concise_winning_summary",
        "innovation_basis",
        "s5_innovation_mechanism_score",
        "naming_assessment_status",
        "naming_new_quality",
        "naming_semantic_alignment",
        "naming_semantics_aligned",
        "naming_anchor",
        "naming_reason",
        "frontier_principle",
        "technology_discontinuity",
        "core_disruptive_difference",
        "disruption_tier",
        "displaced_operational_mode",
        "new_operational_mode",
        "winning_relation_shift",
    )
    result = {
        key: compact(brief[key])
        for key in fields
        if brief.get(key) not in (None, "", [], {})
    }
    result["handoff_contract"] = load_dynamic_winning_prompt(
        "common", section="s6.handoff_contract"
    )
    return result


def _dynamic_s6_card_input(
    brief: Mapping[str, Any],
    *,
    query: str,
) -> dict[str, Any]:
    """Build the only context a dynamic S6 writer is allowed to see.

    S6 is a semantic author, not an S5 form filler. The model receives the
    Query boundary, one candidate identity, a compact authoring context and a
    winning-logic spine. Evidence identifiers, score sheets, indicators,
    validation plans and portfolio metadata stay outside the model call.
    """

    candidate = {
        key: str(brief.get(key, "")).strip()
        for key in (
            "name",
            "primary_equipment_identity",
            "equipment_form",
            "target_and_direct_effect",
        )
        if str(brief.get(key, "")).strip()
    }
    overview = str(
        brief.get("concise_winning_summary")
        or brief.get("reference_overview")
        or brief.get("unique_operational_role")
        or ""
    ).strip()
    authoring_fields = (
        "non_substitutable_difference",
        "innovation_basis",
        "displaced_operational_mode",
        "new_operational_mode",
        "winning_relation_shift",
    )
    authoring_context: dict[str, Any] = {}
    for field in authoring_fields:
        value = brief.get(field)
        if value in (None, "", [], {}):
            continue
        if field == "innovation_basis" and re.search(
            r"(?:创新性|需求性|科学可行性|效能性|研制难度)\s*=",
            str(value),
        ):
            continue
        authoring_context[field] = _compact_prompt_value(
            value,
            max_string_chars=720,
            max_list_items=4,
        )
    if authoring_context:
        candidate["authoring_context"] = authoring_context
    if overview:
        candidate["overview"] = _compact_prompt_value(overview, max_string_chars=900)

    binding_id = str(brief.get("card_binding_id", "")).strip()
    hypothesis_id = str(brief.get("hypothesis_id", "")).strip()
    if binding_id:
        candidate["card_binding_id"] = binding_id
    if hypothesis_id:
        candidate["hypothesis_id"] = hypothesis_id

    logic_labels = load_dynamic_winning_json(
        "common", section="s6.handoff_logic_labels"
    )
    if not isinstance(logic_labels, Mapping):
        logic_labels = {}
    logic_parts: list[str] = []
    for key, label in (
        ("concise_winning_summary", logic_labels.get("concise_winning_summary", "")),
        ("innovation_basis", logic_labels.get("innovation_basis", "")),
        ("displaced_operational_mode", logic_labels.get("displaced_operational_mode", "")),
        ("new_operational_mode", logic_labels.get("new_operational_mode", "")),
        ("winning_relation_shift", logic_labels.get("winning_relation_shift", "")),
    ):
        value = str(brief.get(key, "") or "").strip()
        if key == "innovation_basis" and re.search(
            r"(?:创新性|需求性|科学可行性|效能性|研制难度)\s*=",
            value,
        ):
            continue
        if value:
            logic_parts.append(f"{label}：{value}")
    if not logic_parts:
        for key, label in (
            ("winning_mechanism", logic_labels.get("winning_mechanism", "")),
            ("non_substitutable_difference", logic_labels.get("non_substitutable_difference", "")),
        ):
            value = str(brief.get(key, "") or "").strip()
            if value:
                logic_parts.append(f"{label}：{value}")
    winning_logic = "；".join(logic_parts)
    return {
        "query_semantics": str(query or brief.get("query_relevance", "")).strip(),
        "candidate_weapon": candidate,
        "winning_logic_overview": winning_logic,
    }


def _dynamic_s6_input_fingerprint(payload: Mapping[str, Any]) -> str:
    """Identify the semantic input and fixed quality contract of a cached card."""

    serialized = json.dumps(
        {
            "quality_contract_version": S6_PORTRAIT_QUALITY_CONTRACT_VERSION,
            "semantic_input": payload,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(serialized.encode("utf-8")).hexdigest()


def _minimal_portfolio_candidate_handoff(
    item: Any,
    *,
    rich: bool = False,
) -> dict[str, Any]:
    """Expose the frozen candidate spine to S5 without leaking the ledger.

    The default remains the historical three-field handoff for compatibility
    with older callers.  The full-pool reviewer can opt into the compact
    semantic spine so it can judge a creative name against the actual weapon
    architecture rather than guessing from a title alone.
    """

    result = {
        "hypothesis_id": str(item.hypothesis_id),
        "name": str(item.title),
        "concise_winning_summary": str(item.reference_overview),
    }
    if not rich:
        return result
    equipment_form = str(_winning_primary_equipment_form(item) or item.title).strip()
    result.update(
        {
            "primary_equipment_identity": equipment_form,
            "winning_angle_id": str(getattr(item, "winning_angle_id", "") or "").strip(),
            "combat_dimension": str(getattr(item, "combat_dimension", "") or "").strip(),
            "dimension_winning_logic": str(
                getattr(item, "dimension_winning_logic", "") or ""
            ).strip(),
            "dimension_task_chain_breakpoint": str(
                getattr(item, "dimension_task_chain_breakpoint", "") or ""
            ).strip(),
            "dimension_engagement_geometry": str(
                getattr(item, "dimension_engagement_geometry", "") or ""
            ).strip(),
            "dimension_time_space_position": str(
                getattr(item, "dimension_time_space_position", "") or ""
            ).strip(),
            "dimension_desired_direct_result": str(
                getattr(item, "dimension_desired_direct_result", "") or ""
            ).strip(),
            "frontier_principle": str(item.frontier_principle).strip(),
            "technology_discontinuity": str(item.technology_discontinuity).strip(),
            "core_disruptive_difference": str(item.core_disruptive_difference).strip(),
            "naming_style": str(item.naming_style).strip(),
            "naming_rationale": str(item.naming_rationale).strip(),
            "winning_relation_shift": str(
                item.disruptive_shift or item.changed_confrontation_variable
            ).strip(),
            "direct_military_effects": list(item.direct_military_effects[:2]),
        }
    )
    semantic_parts = [
        str(result.get("primary_equipment_identity", "")).strip(),
        str(result.get("frontier_principle", "")).strip(),
        str(result.get("technology_discontinuity", "")).strip(),
        str(result.get("core_disruptive_difference", "")).strip(),
        str(result.get("winning_relation_shift", "")).strip(),
        "；".join(
            str(value).strip()
            for value in item.direct_military_effects[:2]
            if str(value).strip()
        ),
    ]
    compact_spine = "；".join(value for value in semantic_parts if value)
    if compact_spine:
        result["semantic_spine"] = compact_spine[:1200]
    return {
        key: value for key, value in result.items() if value not in (None, "", [], {})
    }


def _dynamic_portfolio_innovation_priority(
    item: Any,
    reviewer_priority: float | None = None,
) -> float:
    """Return the S5 innovation-first order signal without a keyword gate.

    The isolated reviewer owns the substantive judgement. The structural
    fallback only keeps older/fake-provider runs deterministic when that
    optional field is absent; it rewards explicit frontier/discontinuity and
    disruptive-relation authorship rather than Chinese token matches.
    """

    if reviewer_priority is not None:
        return round(max(0.0, min(1.0, float(reviewer_priority))), 4)
    structural_fields = (
        "frontier_principle",
        "technology_discontinuity",
        "disruptive_shift",
        "core_disruptive_difference",
        "independence_thesis",
        "novelty_delta",
    )
    authored = sum(
        bool(str(getattr(item, key, "") or "").strip()) for key in structural_fields
    )
    return round(min(0.74, 0.44 + authored * 0.05), 4)


_S5_DISRUPTION_TIER_RANK = {
    "incremental_upgrade": 0,
    "significant_innovation": 2,
    "new_quality_breakthrough": 3,
    "paradigm_disruption": 4,
}

# S5's portfolio decision is a weighted model judgement.  These weights are
# deliberately kept in one place so prompt language, deterministic ordering,
# fallback behaviour and the UI all use the same rubric.
S5_DIMENSION_WEIGHTS: dict[str, float] = {
    "innovation": 0.30,
    "demand": 0.30,
    "feasibility": 0.20,
    "effectiveness": 0.10,
    "development": 0.10,
}

S5_INNOVATION_COMPONENT_WEIGHTS: dict[str, float] = {
    "mechanism": 0.75,
    "naming_new_quality": 0.15,
    "naming_semantic_alignment": 0.10,
}


def _s5_numeric_score(value: Any) -> float | None:
    """Parse an explicit model score without inferring one from prose."""

    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        return round(max(0.0, min(1.0, float(value))), 4)
    except (TypeError, ValueError):
        return None


def _s5_naming_assessment(value: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize the model-owned naming review and its mechanism anchor.

    Naming quality is deliberately opaque to local code: this helper only
    transports explicit numeric judgements and model-authored explanations.
    It never derives novelty from name length, characters, keywords or a
    fixed vocabulary.
    """

    nested: dict[str, Any] = {}
    for key in ("innovation_components", "naming_assessment"):
        candidate = value.get(key)
        if isinstance(candidate, Mapping):
            nested.update(candidate)
    raw_dimensions = value.get("dimension_scores")
    raw_dimensions = raw_dimensions if isinstance(raw_dimensions, Mapping) else {}

    def first(keys: Sequence[str]) -> Any:
        for key in keys:
            if value.get(key) not in (None, ""):
                return value.get(key)
            if nested.get(key) not in (None, ""):
                return nested.get(key)
            if raw_dimensions.get(key) not in (None, ""):
                return raw_dimensions.get(key)
        return None

    declared_status = str(value.get("naming_assessment_status", "") or "").strip().lower()
    if declared_status in {"unassessed", "not_assessed", "未评审", "未评估"}:
        return {
            "status": "unassessed",
            "s5_innovation_mechanism_score": None,
            "naming_new_quality": None,
            "naming_semantic_alignment": None,
            "effective_innovation": None,
            "naming_anchor": str(
                value.get("naming_anchor")
                or value.get("name_semantic_anchor")
                or ""
            ).strip()[:240],
            "naming_reason": str(
                value.get("naming_reason")
                or value.get("naming_rationale")
                or ""
            ).strip()[:500],
        }

    mechanism_score = _s5_numeric_score(
        first(
            (
                "s5_innovation_mechanism_score",
                "innovation_mechanism_score",
                "mechanism_innovation_score",
                "mechanism_innovation",
                "装备机理创新性",
                "机理创新性",
            )
        )
    )
    naming_new_quality = _s5_numeric_score(
        first(
            (
                "naming_new_quality",
                "naming_innovation",
                "naming_novelty",
                "命名新质度",
                "命名创新性",
            )
        )
    )
    naming_semantic_alignment = _s5_numeric_score(
        first(
            (
                "naming_semantic_alignment",
                "naming_alignment",
                "name_semantic_alignment",
                "命名与本体一致性",
                "名称语义一致性",
            )
        )
    )
    # A legacy provider may put the extended assessment in prose instead of
    # emitting the new nested fields.  Parse only explicit ``label=number``
    # statements; never infer a score from the name itself.
    basis_text = " ".join(
        str(value.get(key, "") or "")
        for key in ("innovation_basis", "reason", "score_basis")
    )

    def score_from_text(
        current: float | None,
        aliases: Sequence[str],
    ) -> float | None:
        if current is not None:
            return current
        for alias in aliases:
            match = re.search(
                rf"{re.escape(alias)}\s*[=:：]\s*(0(?:\.\d+)?|1(?:\.0+)?)",
                basis_text,
                flags=re.IGNORECASE,
            )
            if match:
                return _s5_numeric_score(match.group(1))
        return None

    mechanism_score = score_from_text(
        mechanism_score,
        (
            "机理/装备创新性",
            "装备机理创新性",
            "机理创新性",
            "innovation_mechanism",
        ),
    )
    naming_new_quality = score_from_text(
        naming_new_quality,
        ("命名新质度", "命名创新性", "naming_new_quality", "naming_innovation"),
    )
    naming_semantic_alignment = score_from_text(
        naming_semantic_alignment,
        (
            "命名与本体一致性",
            "名称语义一致性",
            "naming_semantic_alignment",
            "naming_alignment",
        ),
    )
    complete = all(
        score is not None
        for score in (
            mechanism_score,
            naming_new_quality,
            naming_semantic_alignment,
        )
    )
    if complete:
        effective_innovation = round(
            mechanism_score * S5_INNOVATION_COMPONENT_WEIGHTS["mechanism"]
            + naming_new_quality
            * S5_INNOVATION_COMPONENT_WEIGHTS["naming_new_quality"]
            + naming_semantic_alignment
            * S5_INNOVATION_COMPONENT_WEIGHTS["naming_semantic_alignment"],
            4,
        )
        status = "assessed"
    elif any(
        score is not None
        for score in (
            mechanism_score,
            naming_new_quality,
            naming_semantic_alignment,
        )
    ):
        effective_innovation = None
        status = "incomplete"
    else:
        effective_innovation = None
        status = "unassessed"
    return {
        "status": status,
        "s5_innovation_mechanism_score": mechanism_score,
        "naming_new_quality": naming_new_quality,
        "naming_semantic_alignment": naming_semantic_alignment,
        "effective_innovation": effective_innovation,
        "naming_anchor": str(
            value.get("naming_anchor")
            or value.get("name_semantic_anchor")
            or nested.get("naming_anchor")
            or ""
        ).strip()[:240],
        "naming_reason": str(
            value.get("naming_reason")
            or value.get("naming_rationale")
            or nested.get("naming_reason")
            or ""
        ).strip()[:500],
    }


def _s5_dimension_scores(value: Mapping[str, Any]) -> tuple[dict[str, float], float]:
    """Normalize the model's five S5 scores and calculate the weighted total."""

    raw = value.get("dimension_scores", {})
    raw = raw if isinstance(raw, Mapping) else {}
    # Keep the wire contract compact/backward compatible: providers that use
    # the historical decision schema may place the five values in
    # innovation_basis as ``创新性=0.82；需求性=0.76`` (or English aliases).
    # This parser only transports the model's judgement; it never invents a
    # novelty score from local keywords.
    basis_text = " ".join(
        str(value.get(key, "") or "")
        for key in ("innovation_basis", "reason", "score_basis")
    )
    score_aliases = {
        "innovation": ("innovation", "创新性"),
        "demand": ("demand", "需求性"),
        "feasibility": ("feasibility", "科学可行性", "可行性"),
        "effectiveness": ("effectiveness", "效能性"),
        "development": ("development", "发展性"),
    }
    if not raw:
        raw = {
            dimension: match.group(1)
            for dimension, aliases_for_dimension in score_aliases.items()
            for alias in aliases_for_dimension
            for match in [
                re.search(
                    rf"{re.escape(alias)}\s*[=:：]\s*(0(?:\.\d+)?|1(?:\.0+)?)",
                    basis_text,
                    flags=re.IGNORECASE,
                )
            ]
            if match
        }
    aliases = {
        "innovation": ("innovation", "创新性"),
        "demand": ("demand", "需求性"),
        "feasibility": (
            "feasibility",
            "可行性",
            "scientific_feasibility",
            "科学可行性",
        ),
        "effectiveness": ("effectiveness", "效能性"),
        "development": ("development", "发展性"),
    }
    scores: dict[str, float] = {}
    for dimension, keys in aliases.items():
        candidate = next(
            (raw.get(key) for key in keys if raw.get(key) not in (None, "")),
            None,
        )
        # Older/fallback reviewers only emitted innovation_priority. Preserve
        # their judgement rather than turning every legacy row into a zero;
        # unreported non-innovation dimensions remain neutral (0.5) until a
        # weighted S5 reviewer supplies them explicitly.
        if candidate in (None, ""):
            candidate = (
                value.get("innovation_priority") if dimension == "innovation" else 0.5
            )
        try:
            score = float(candidate)
        except (TypeError, ValueError):
            score = 0.0
        scores[dimension] = round(max(0.0, min(1.0, score)), 4)
    naming_assessment = _s5_naming_assessment(value)
    # New S5 reviewers provide all three components explicitly.  Older
    # providers omit them and retain the historical innovation score exactly.
    if naming_assessment["status"] == "assessed":
        scores["innovation"] = naming_assessment["effective_innovation"]
    # The five model-authored dimensions are authoritative. Always recompute
    # the total locally so a rounding mistake or an inconsistent provider
    # total cannot silently change the requested 30/30/20/10/10 ranking.
    weighted = sum(
        scores[dimension] * weight for dimension, weight in S5_DIMENSION_WEIGHTS.items()
    )
    return scores, round(max(0.0, min(1.0, weighted)), 4)


def _s5_innovation_basis(
    value: Mapping[str, Any],
    *,
    dimension_scores: Mapping[str, Any] | None = None,
    naming_assessment: Mapping[str, Any] | None = None,
) -> str:
    """Keep the final innovation basis consistent with the recomputed score."""

    naming = (
        dict(naming_assessment)
        if isinstance(naming_assessment, Mapping)
        else _s5_naming_assessment(value)
    )
    raw_text = str(value.get("innovation_basis", "") or "").strip()
    if naming.get("status") != "assessed":
        return raw_text[:500]
    scores = (
        dict(dimension_scores)
        if isinstance(dimension_scores, Mapping)
        else _s5_dimension_scores(value)[0]
    )
    canonical = load_dynamic_winning_prompt(
        "common", section="s5.assessed_score_basis"
    ).format(
        innovation=float(scores.get("innovation", 0.0) or 0.0),
        demand=float(scores.get("demand", 0.0) or 0.0),
        feasibility=float(scores.get("feasibility", 0.0) or 0.0),
        effectiveness=float(scores.get("effectiveness", 0.0) or 0.0),
        development=float(scores.get("development", 0.0) or 0.0),
        mechanism=float(naming.get("s5_innovation_mechanism_score") or 0.0),
        new_quality=float(naming.get("naming_new_quality") or 0.0),
        alignment=float(naming.get("naming_semantic_alignment") or 0.0),
    )
    if raw_text:
        score_prefix = re.compile(
            r"^\s*创新性\s*=[^；;]*[；;]\s*需求性\s*=[^；;]*[；;]"
            r"\s*科学可行性\s*=[^；;]*[；;]\s*效能性\s*=[^；;]*[；;]"
            r"\s*发展性\s*=[^；;]*[；;]\s*"
        )
        raw_text = score_prefix.sub("", raw_text, count=1).strip()
    details = [
        load_dynamic_winning_prompt(
            "common", section="s5.assessed_naming_anchor"
        ).format(value=str(naming.get("naming_anchor", "") or "").strip()),
        load_dynamic_winning_prompt(
            "common", section="s5.assessed_naming_reason"
        ).format(value=str(naming.get("naming_reason", "") or "").strip()),
    ]
    suffix = "；".join(item for item in details if not item.endswith("="))
    return (canonical + raw_text + ("；" if raw_text and suffix else "") + suffix)[:900]


def _s5_disruption_tier_rank(
    value: Any,
    innovation_priority: float | None = None,
) -> int:
    """Order explicit paradigm breaks ahead of ordinary high-score prose."""

    normalized = str(value or "").strip().lower()
    if normalized in _S5_DISRUPTION_TIER_RANK:
        return _S5_DISRUPTION_TIER_RANK[normalized]
    try:
        priority = (
            float(innovation_priority) if innovation_priority is not None else 0.0
        )
    except (TypeError, ValueError):
        priority = 0.0
    if priority >= 0.80:
        return 3
    if priority >= 0.65:
        return 2
    return 1


def _s5_retain_passes_concrete_weapon_contract(
    value: Mapping[str, Any],
    *,
    query_domain_mode: str = "direct_combat",
) -> bool:
    """Honor S5's explicit object, naming and plausibility judgement.

    Older providers did not emit the two newer specificity flags, so missing
    values remain backward compatible. Any explicit judgement that the item is
    support-dependent or not a concrete direct weapon prevents retention for a
    combat Query. Mission-equipment Queries use the same quality checks while
    allowing a detector/sensor/diagnostic object to be non-combat by design.
    """

    # ``codename_or_metaphor_explainable`` is conditional on the naming
    # style.  An explicit non-codename style (for example ``physical_form``)
    # is allowed to report ``false`` because the check does not apply.  When
    # the style is omitted, however, keep the historical fail-closed behavior
    # for an explicit ``false``: older reviewers used this flag as the only
    # available naming-semantic gate.  This preserves compatibility without
    # rejecting a reviewer that clearly identifies an ordinary physical name.
    naming_style = str(value.get("naming_style", "")).strip().lower()
    codename_check_failed = value.get("codename_or_metaphor_explainable") is False and (
        not naming_style
        or naming_style in {"codename", "metaphor", "codename_or_metaphor"}
    )
    original_name = str(value.get("name", "") or "").strip()
    final_name = str(value.get("final_name", "") or "").strip()
    naming_repaired = bool(final_name) and bool(
        value.get("name_changed") is True
        or (original_name and final_name != original_name)
    )
    naming_alignment_low = False
    explicit_alignment = value.get("naming_semantic_alignment")
    if explicit_alignment not in (None, "") and not isinstance(explicit_alignment, bool):
        try:
            naming_alignment_low = float(explicit_alignment) <= 0.30
        except (TypeError, ValueError):
            naming_alignment_low = False
    mission_equipment = str(query_domain_mode).strip().lower() == "mission_equipment"
    combat_object_gate_failed = (
        not mission_equipment
        and (
            value.get("direct_equipment") is False
            or value.get("weapon_object_specific") is False
            or value.get("weapon_body_mechanism_closes") is False
        )
    )
    return not (
        combat_object_gate_failed
        or value.get("support_dependency_only") is True
        or (value.get("naming_semantics_aligned") is False and not naming_repaired)
        or (naming_alignment_low and not naming_repaired)
        or codename_check_failed
        or value.get("known_science_consistent") is False
        or value.get("material_innovation_breakpoint_present") is False
        or value.get("ordinary_upgrade_or_function_packaging") is True
        or str(value.get("disruption_tier", "")).strip().lower()
        == "incremental_upgrade"
    )


def _s5_portfolio_fallback_result(
    candidates: Sequence[Any],
    *,
    maximum: int = 7,
) -> dict[str, Any]:
    """Build a conservative S5 result when the reviewer provider is unavailable.

    This is deliberately a transport-resilience path, not a second reviewer.
    It never invents a weapon, mechanism, name, or military effect.  It only
    orders the semantic material already authored by S3/S4 and keeps a small
    set of direct-combat candidates alive so one provider-capacity failure does
    not turn an otherwise usable run into ``limited S5``.
    """

    def field(item: Any, name: str, default: Any = "") -> Any:
        """Read both ledger objects and compact mapping envelopes."""

        if isinstance(item, Mapping):
            return item.get(name, default)
        return getattr(item, name, default)

    # Keep the transport fallback bounded by the same hard portfolio cap as
    # the normal S5 path, even when a caller supplies an untrusted policy
    # value.  A provider outage must not expand S6 work accidentally.
    limit = max(1, min(7, int(maximum)))
    rows: list[tuple[Any, int, float]] = []
    excluded: list[tuple[Any, str, str]] = []
    for item in candidates:
        implementation_path = str(
            field(item, "implementation_path") or ""
        ).strip().lower()
        # An explicitly labelled upgrade/support branch has no independent
        # S5 innovation judgement during fallback.  Leave it out so the
        # dynamic decision repair below synthesizes a reject instead of
        # quietly promoting it to a finalist.
        if implementation_path in {
            "upgrade",
            "system_link",
            "system-link",
            "non_materiel",
            "non-materiel",
            "support",
        }:
            excluded.append(
                (
                    item,
                    load_dynamic_winning_prompt(
                        "common", section="s5.fallback.excluded_upgrade"
                    ).strip(),
                    "explicit_upgrade_or_support_path",
                )
            )
            continue
        direct_effects = [
            str(value).strip()
            for value in field(item, "direct_military_effects", [])
            if str(value).strip()
        ]
        equipment_forms = [
            str(value).strip()
            for value in field(item, "equipment_forms", [])
            if str(value).strip()
        ]
        if not direct_effects or not equipment_forms:
            # A support-only or structurally empty branch is not rescued by a
            # transport fallback.  S5 remains the authority on membership.
            excluded.append(
                (
                    item,
                    load_dynamic_winning_prompt(
                        "common", section="s5.fallback.excluded_missing_weapon"
                    ).strip(),
                    "missing_direct_weapon_fields",
                )
            )
            continue
        authored_fields = (
            "frontier_principle",
            "technology_discontinuity",
            "core_disruptive_difference",
            "disruptive_shift",
            "independence_thesis",
            "novelty_delta",
        )
        spine_count = sum(
            bool(str(field(item, field_name) or "").strip())
            for field_name in authored_fields
        )
        try:
            score = float(field(item, "score", 0.0) or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        rows.append((item, spine_count, score))

    rows.sort(
        key=lambda row: (
            -row[1],
            -row[2],
            str(field(row[0], "hypothesis_id")),
        )
    )
    # Apply the same two-level portfolio rule as the normal S5 path.  The
    # fallback has no model-authored five-axis scores, so it derives only a
    # conservative transport score from already-authored semantic fields;
    # it still must not spend all seven slots on one explicit dimension.
    fallback_weighted_scores: dict[str, float] = {}
    fallback_priorities: dict[str, float] = {}
    fallback_tiers: dict[str, str] = {}
    fallback_order_hints: dict[str, int] = {}
    for index, (item, spine_count, _score) in enumerate(rows):
        hypothesis_id = str(field(item, "hypothesis_id") or "")
        if not hypothesis_id:
            continue
        direct_effects = [
            value
            for value in field(item, "direct_military_effects", [])
            if str(value).strip()
        ]
        changed_variable = str(
            field(item, "changed_confrontation_variable") or ""
        ).strip()
        dimension_scores = {
            "innovation": round(min(1.0, 0.34 + 0.08 * spine_count), 4),
            "demand": 0.70 if changed_variable else 0.50,
            "feasibility": 0.55,
            "effectiveness": 0.70 if direct_effects else 0.50,
            "development": 0.55,
        }
        fallback_weighted_scores[hypothesis_id] = round(
            sum(
                dimension_scores[name] * weight
                for name, weight in S5_DIMENSION_WEIGHTS.items()
            ),
            4,
        )
        fallback_priorities[hypothesis_id] = round(
            min(0.82, 0.34 + 0.08 * spine_count),
            4,
        )
        fallback_tiers[hypothesis_id] = (
            "new_quality_breakthrough"
            if spine_count >= 4
            else "significant_innovation"
            if spine_count >= 2
            else ""
        )
        fallback_order_hints[hypothesis_id] = index
    selected_items, portfolio_diversity_audit = _s5_diverse_portfolio_order(
        [item for item, _spine, _score in rows],
        weighted_scores=fallback_weighted_scores,
        innovation_priorities=fallback_priorities,
        disruption_tiers=fallback_tiers,
        portfolio_order_hints=fallback_order_hints,
        maximum=limit,
    )
    selected_ids = {
        str(field(item, "hypothesis_id")) for item in selected_items
    }
    decisions: list[dict[str, Any]] = []
    for item, spine_count, _score in rows:
        hypothesis_id = str(field(item, "hypothesis_id"))
        direct_effects = [
            str(value).strip()
            for value in field(item, "direct_military_effects", [])
            if str(value).strip()
        ]
        frontier = str(field(item, "frontier_principle") or "").strip()
        discontinuity = str(field(item, "technology_discontinuity") or "").strip()
        disruptive_difference = str(
            field(item, "core_disruptive_difference") or ""
        ).strip()
        disruptive_shift = str(field(item, "disruptive_shift") or "").strip()
        changed_variable = str(
            field(item, "changed_confrontation_variable") or ""
        ).strip()
        innovation_basis = "；".join(
            value
            for value in (
                frontier,
                discontinuity,
                disruptive_difference,
                disruptive_shift,
            )
            if value
        )[:500]
        dimension_scores = {
            "innovation": round(min(1.0, 0.34 + 0.08 * spine_count), 4),
            "demand": 0.70 if changed_variable else 0.50,
            "feasibility": 0.55,
            "effectiveness": 0.70 if direct_effects else 0.50,
            "development": 0.55,
        }
        weighted_score = round(
            sum(
                dimension_scores[name] * weight
                for name, weight in S5_DIMENSION_WEIGHTS.items()
            ),
            4,
        )
        innovation_basis = load_dynamic_winning_prompt(
            "common", section="s5.score_basis"
        ).format(**dimension_scores, basis=innovation_basis)
        if spine_count >= 4:
            disruption_tier = "new_quality_breakthrough"
        elif spine_count >= 2:
            disruption_tier = "significant_innovation"
        else:
            # Leave the tier open when S3/S4 did not author enough explicit
            # innovation prose.  The candidate can still survive as a lower-
            # priority reference, but we must not fabricate a breakthrough.
            disruption_tier = ""
        decisions.append(
            {
                "hypothesis_id": hypothesis_id,
                "decision": "retain" if hypothesis_id in selected_ids else "reject",
                "reason": (
                    load_dynamic_winning_prompt(
                        "common", section="s5.fallback.retained_reason"
                    ).strip()
                    if hypothesis_id in selected_ids
                    else load_dynamic_winning_prompt(
                        "common", section="s5.fallback.rejected_reason"
                    ).strip()
                ),
                "independence_basis": changed_variable,
                "innovation_priority": round(
                    min(0.82, 0.34 + 0.08 * spine_count),
                    4,
                ),
                "innovation_basis": innovation_basis,
                "dimension_scores": dimension_scores,
                "weighted_score": weighted_score,
                "disruption_tier": disruption_tier,
                # ``None`` means the fallback did not make a new semantic
                # judgement.  Explicit false would incorrectly reject a
                # candidate through the normal S5 contract gate.
                "material_innovation_breakpoint_present": (
                    True if spine_count >= 2 else None
                ),
                "ordinary_upgrade_or_function_packaging": None,
                "displaced_operational_mode": str(
                    field(item, "original_paradigm") or ""
                ).strip()[:500],
                "new_operational_mode": disruptive_shift[:500],
                "winning_relation_shift": changed_variable[:500],
                "direct_equipment": True,
                "weapon_object_specific": True,
                "support_dependency_only": False,
                "naming_semantics_aligned": True,
                "codename_or_metaphor_explainable": True,
                "known_science_consistent": True,
                "weapon_body_mechanism_closes": True,
                "final_name": str(field(item, "title") or "").strip(),
                "name_changed": False,
                "naming_style": str(field(item, "naming_style") or "").strip(),
                "naming_assessment_status": "unassessed",
                "s5_innovation_mechanism_score": None,
                "naming_new_quality": None,
                "naming_semantic_alignment": None,
                "naming_anchor": "",
                "naming_reason": load_dynamic_winning_prompt(
                    "common", section="s5.fallback.naming_reason"
                ).strip(),
                "functional_splice_detected": False,
            }
        )
    # Keep an explicit reject row for every candidate excluded by the
    # transport fallback.  The dynamic controller can therefore distinguish
    # a deliberate conservative rejection from a truncated provider envelope;
    # it also avoids silently re-admitting an ordinary upgrade on a later
    # portfolio backfill.
    for item, reason, exclusion_code in excluded:
        hypothesis_id = str(field(item, "hypothesis_id"))
        if not hypothesis_id:
            continue
        decisions.append(
            {
                "hypothesis_id": hypothesis_id,
                "decision": "reject",
                "reason": reason,
                "independence_basis": "",
                "innovation_priority": 0.0,
                "innovation_basis": reason,
                "dimension_scores": {
                    "innovation": 0.0,
                    "demand": 0.0,
                    "feasibility": 0.0,
                    "effectiveness": 0.0,
                    "development": 0.0,
                },
                "weighted_score": 0.0,
                "disruption_tier": "incremental_upgrade",
                "material_innovation_breakpoint_present": False,
                "ordinary_upgrade_or_function_packaging": (
                    exclusion_code == "explicit_upgrade_or_support_path"
                ),
                "direct_equipment": False,
                "weapon_object_specific": False,
                "support_dependency_only": True,
                "known_science_consistent": True,
                "weapon_body_mechanism_closes": False,
                "naming_semantics_aligned": True,
                "codename_or_metaphor_explainable": True,
                "naming_assessment_status": "unassessed",
                "s5_innovation_mechanism_score": None,
                "naming_new_quality": None,
                "naming_semantic_alignment": None,
                "naming_anchor": "",
                "naming_reason": load_dynamic_winning_prompt(
                    "common", section="s5.fallback.excluded_naming_reason"
                ).strip(),
                "functional_splice_detected": False,
            }
        )
    return {
        "decisions": decisions,
        "portfolio_order": [
            str(field(item, "hypothesis_id")) for item in selected_items
        ],
        "portfolio_diversity_audit": portfolio_diversity_audit,
        "portfolio_summary": load_dynamic_winning_prompt(
            "common", section="s5.fallback.portfolio_summary"
        ).strip(),
        "stop_reason": "provider_capacity_fallback",
    }


def _compact_s6_authored_card_event(direction: Mapping[str, Any]) -> dict[str, Any]:
    """Publish one bounded but complete S6 card for live API projection."""

    keep = (
        "hypothesis_id",
        "card_binding_id",
        "name",
        "source_hypothesis_title",
        "type",
        "primary_equipment_identity",
        "equipment_form",
        "equipment_family",
        "unique_operational_role",
        "launch_or_release_domain",
        "target_and_direct_effect",
        "non_substitutable_difference",
        "baseline_system",
        "capability_gap",
        "target_scenario",
        "function",
        "operational_mechanism",
        "operational_process",
        "capability_outcome",
        "military_value",
        "winning_mechanism",
        "capability_portrait",
        "capability_portrait_modules",
        "portrait_module_character_counts",
        "portrait_quality_contract_version",
        "semantic_consistency_check",
        "s6_authoring_status",
        "s6_authoring_quality_warnings",
        "s6_authoring_audit_notes",
        "system_contribution_thesis",
        "indicator_portrait",
        "query_relevance",
        "direct_evidence_refs",
        "evidence_boundary",
        "validation_plan",
        "adversary_adaptation",
        "priority",
        "confidence",
        "expert_score",
        "verification_status",
        "confidence_limited",
        "confidence_components",
        "selection_quality_status",
        "capability_classification",
        "direct_combat_equipment",
        "disruption_tier",
        "displaced_operational_mode",
        "new_operational_mode",
        "winning_relation_shift",
        "innovation_basis",
    )
    return {
        key: _compact_prompt_value(
            direction.get(key),
            max_string_chars=2400 if key == "capability_portrait" else 520,
            max_list_items=12,
        )
        for key in keep
        if direction.get(key) not in (None, "", [], {})
    }


def _quality_cluster_candidate_instruction() -> str:
    """Keep quality-cluster breadth creative while preserving evidence discipline."""

    return (
        load_dynamic_winning_prompt("common", section="quality_swarm.breadth")
        + load_dynamic_winning_prompt("common", section="naming_convention")
    )


def _parallel_s6_card_instruction() -> str:
    """Return the single Markdown-owned contract for an isolated S6 card."""

    return load_dynamic_winning_prompt("S6")


def _dynamic_s6_spine_instruction() -> str:
    """Return the dynamic-v2 contract for non-portrait judgement fields."""

    return load_dynamic_winning_prompt("S6", section="spine")


def _dynamic_s6_module_instruction(
    module_key: str,
    *,
    module_guidance: str = "",
) -> str:
    """Return the isolated single-column authoring contract for one portrait module."""

    labels = {key: label for key, label in CAPABILITY_PORTRAIT_MODULES}
    label = labels.get(module_key, module_key)
    guidance = module_guidance or _dynamic_s6_module_guidance(module_key)
    return (
        load_dynamic_winning_prompt("S6", section="module")
        + load_dynamic_winning_prompt("S6", section="module_instruction_suffix").format(
            guidance=guidance,
            label=label,
            module_key=module_key,
        )
    )


def _dynamic_s6_module_guidance(module_key: str) -> str:
    """Load the per-column authoring brief from the Markdown prompt resource."""

    section_by_module = {
        "overview": "S6_1",
        "technology_implementation": "S6_2",
        "operational_process": "S6_3",
        "capability_effects": "S6_4",
        "winning_logic": "S6_5",
    }
    try:
        section = section_by_module[module_key]
    except KeyError as exc:
        raise ValueError(f"unknown S6 portrait module: {module_key!r}") from exc
    return load_dynamic_winning_prompt("S6", section=section)


def _s6_portrait_module_lengths(modules: Mapping[str, Any] | object) -> dict[str, int]:
    """Count substantive CJK characters in each independently authored module."""

    return capability_portrait_module_lengths(modules)


def _s6_short_portrait_modules(modules: Mapping[str, Any] | object) -> list[str]:
    """Return every module below the shared per-column repair trigger."""

    return short_capability_portrait_modules(modules)


def _parallel_s6_short_module_repair_instruction(
    short_module_keys: Sequence[str],
) -> str:
    """Build the one-shot semantic expansion contract for one isolated card."""

    labels = {key: label for key, label in CAPABILITY_PORTRAIT_MODULES}
    short_labels = "、".join(labels.get(key, key) for key in short_module_keys)
    return load_dynamic_winning_prompt("S6", section="short_module_repair").format(
        short_labels=short_labels
    )


def _dynamic_s6_module_repair_instruction(module_key: str) -> str:
    """Build a single-column repair contract for dynamic concurrent authoring."""

    labels = {key: label for key, label in CAPABILITY_PORTRAIT_MODULES}
    label = labels.get(module_key, module_key)
    return load_dynamic_winning_prompt("S6", section="module_repair").format(
        label=label,
        module_key=module_key,
    )


def _parallel_s6_quality_repair_instruction(quality_issues: Sequence[str]) -> str:
    """Build an optional second-pass editor contract.

    This pass is best-effort only. The caller keeps an immutable first-pass
    snapshot and replaces it only after the returned card is structurally
    complete and identity-safe.
    """

    issue_text = "；".join(str(item) for item in quality_issues[:8])
    return load_dynamic_winning_prompt("S6", section="quality_repair").format(
        issue_text=issue_text
    )


def _extract_s6_direction(parsed: Mapping[str, Any] | object) -> dict[str, Any]:
    """Accept harmless wrapper drift from a structured S6 response."""

    if not isinstance(parsed, Mapping):
        return {}
    nested = parsed.get("direction")
    if isinstance(nested, Mapping):
        return dict(nested)
    if any(
        key in parsed
        for key in (
            "capability_portrait_modules",
            "capability_portrait",
            "operational_process",
            "semantic_consistency_check",
        )
    ):
        return {
            str(key): value
            for key, value in parsed.items()
            if key != "capability_image_draft"
        }
    return {}


def _stabilize_s6_direction_structure(
    direction: Mapping[str, Any] | object,
    brief: Mapping[str, Any],
) -> dict[str, Any]:
    """Repair routing/shape drift without inventing substantive prose."""

    stabilized = dict(direction) if isinstance(direction, Mapping) else {}
    for field in (
        "name",
        "card_binding_id",
        "hypothesis_id",
        "source_hypothesis_title",
        "primary_equipment_identity",
        "equipment_form",
        "target_and_direct_effect",
    ):
        frozen = brief.get(field)
        if frozen not in (None, "", [], {}):
            stabilized[field] = frozen

    # Dynamic S6 intentionally emits a compact schema, but the final audit and
    # downstream report still require the frozen S3–S5 semantic spine. Restore
    # omitted fields from the authoritative brief without overwriting any
    # fresh S6 judgement.  Previously these fields silently became empty on
    # publication, so a high-quality portrait was audited as lacking a
    # baseline, mechanism, and novelty rationale.
    for field in (
        "baseline_system",
        "capability_gap",
        "non_substitutable_difference",
        "operational_mechanism",
        "depth_mechanism",
        "novelty",
        "innovation_basis",
        "s5_innovation_mechanism_score",
        "naming_assessment_status",
        "naming_new_quality",
        "naming_semantic_alignment",
        "naming_semantics_aligned",
        "naming_anchor",
        "naming_reason",
        "displaced_operational_mode",
        "new_operational_mode",
        "winning_relation_shift",
        "direct_evidence_refs",
        "evidence_boundary",
        "validation_plan",
    ):
        if str(stabilized.get(field, "") or "").strip() or stabilized.get(field) in ([], {}):
            continue
        frozen = brief.get(field)
        if frozen not in (None, "", [], {}):
            stabilized[field] = frozen

    if not str(stabilized.get("operational_mechanism", "") or "").strip():
        stabilized["operational_mechanism"] = str(
            stabilized.get("winning_mechanism")
            or stabilized.get("non_substitutable_difference")
            or stabilized.get("new_operational_mode")
            or ""
        ).strip()
    if not str(stabilized.get("novelty", "") or "").strip():
        stabilized["novelty"] = str(
            stabilized.get("innovation_basis")
            or stabilized.get("core_disruptive_difference")
            or stabilized.get("non_substitutable_difference")
            or ""
        ).strip()

    process = stabilized.get("operational_process")
    if isinstance(process, str):
        nodes = [item.strip() for item in re.split(r"[\n；]+", process) if item.strip()]
        stabilized["operational_process"] = nodes or [process.strip()]

    modules = stabilized.get("capability_portrait_modules")
    if not isinstance(modules, Mapping):
        parsed_modules = parse_capability_portrait_modules(
            stabilized.get("capability_portrait", "")
        )
        if parsed_modules:
            stabilized["capability_portrait_modules"] = parsed_modules

    semantic_check = stabilized.get("semantic_consistency_check")
    if isinstance(semantic_check, Mapping):
        semantic_check = dict(semantic_check)
        consistent = semantic_check.get("consistent")
        if isinstance(consistent, str):
            normalized = consistent.strip().lower()
            if normalized in {"true", "yes", "1", "是", "一致"}:
                semantic_check["consistent"] = True
            elif normalized in {"false", "no", "0", "否", "不一致"}:
                semantic_check["consistent"] = False
        stabilized["semantic_consistency_check"] = semantic_check
    return stabilized


def _bounded_s6_parallelism(runtime_budgets: Mapping[str, Any] | object) -> int:
    """Resolve the operator setting as a safe cap on concurrent S6 model calls.

    Dynamic S6 fans out up to seven finalists times five portrait modules
    (plus one spine call per card).  The hard ceiling therefore tracks the
    theoretical fan-out rather than the older one-call-per-card budget.
    """

    try:
        operator_limit = int(
            os.environ.get(
                "EQUIPMENT_DR_S6_CODEX_CONCURRENCY",
                str(S6_DEFAULT_CODEX_CONCURRENCY),
            )
        )
    except (TypeError, ValueError):
        operator_limit = S6_DEFAULT_CODEX_CONCURRENCY
    budgets = runtime_budgets if isinstance(runtime_budgets, Mapping) else {}
    try:
        profile_limit = int(budgets.get("s6_codex_concurrency", operator_limit))
    except (TypeError, ValueError):
        profile_limit = operator_limit
    # The S6 lane is intentionally wider than the ordinary research pool. It
    # can overlap five columns and one spine across several weapon cards, but
    # remains bounded so malformed portfolio/config data cannot create an
    # unbounded number of local CLI processes.
    return max(
        1,
        min(
            S6_MAX_CODEX_CONCURRENCY,
            operator_limit,
            profile_limit,
        ),
    )


def _s6_hard_timeout_is_enabled() -> bool:
    """Whether S6 soft timeout thresholds should terminate the provider."""

    configured = (
        str(os.environ.get("EQUIPMENT_DR_S6_HARD_TIMEOUTS", "0")).strip().lower()
    )
    return configured in {
        "1",
        "true",
        "yes",
        "on",
    }


def _s6_card_attempt_limit() -> int:
    """Keep malformed operator settings from breaking the whole portfolio."""

    try:
        # S6 is card-isolated and its output is persisted before Reporter;
        # spend a little more bounded effort here so a transient gateway or
        # malformed structured response does not immediately become a
        # user-visible fallback card.
        configured = int(os.environ.get("EQUIPMENT_DR_S6_CARD_ATTEMPTS", "3"))
    except (TypeError, ValueError):
        configured = 3
    return max(2, min(4, configured))


def _s6_card_timeout_threshold(*, resume: bool) -> int:
    name = (
        "EQUIPMENT_DR_S6_CARD_RESUME_TIMEOUT_SECONDS"
        if resume
        else "EQUIPMENT_DR_S6_CARD_TIMEOUT_SECONDS"
    )
    default = 480 if resume else 420
    try:
        configured = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        configured = default
    return max(180, configured)


def _s6_repair_wall_timeout_seconds() -> float:
    """Return a safe finite wall-clock lease for optional card enhancement."""

    try:
        configured = float(
            os.environ.get("EQUIPMENT_DR_S6_CARD_REPAIR_WALL_SECONDS", "240")
        )
    except (TypeError, ValueError):
        configured = 240.0
    return max(30.0, configured)


def _dynamic_role_contract_handoff(contract: Any, task: Any) -> dict[str, Any]:
    """Expose authority and handoff boundaries without replaying rule lists."""

    node = str(contract.mission_node)
    resource = load_dynamic_winning_json(
        "common", section="dynamic.role_contract_handoff"
    )
    if not isinstance(resource, Mapping):
        raise ValueError("dynamic.role_contract_handoff must be a JSON object")
    authority_catalog = resource.get("authority")
    handoff_catalog = resource.get("handoff")
    prohibitions = resource.get("prohibitions")
    if not isinstance(authority_catalog, Mapping):
        raise ValueError("dynamic.role_contract_handoff.authority must be an object")
    if not isinstance(handoff_catalog, Mapping):
        raise ValueError("dynamic.role_contract_handoff.handoff must be an object")
    if not isinstance(prohibitions, list):
        raise ValueError("dynamic.role_contract_handoff.prohibitions must be a list")
    authority = str(
        authority_catalog.get(node, authority_catalog.get("default", "")) or ""
    ).strip()
    handoff = str(
        handoff_catalog.get(node, handoff_catalog.get("default", "")) or ""
    ).strip()
    normalized_prohibitions = [
        str(item).strip() for item in prohibitions if str(item).strip()
    ]
    if not authority or not handoff or not normalized_prohibitions:
        raise ValueError(
            "dynamic.role_contract_handoff is missing a node/default contract"
        )
    return {
        "contract_id": str(contract.role_contract_id),
        "role": str(task.display_name),
        "mission_node": node,
        "mandate": str(task.purpose),
        "decision_authority": authority,
        "handoff_contract": handoff,
        "prohibitions": normalized_prohibitions,
    }
