"""Domain planner: bounded tool sequences, with model override on follow-ups.

Nanobot lets the model pick tools freely. Directed equipment research keeps
the single-equipment identity and explicit S6 confirmation boundary, while
treating completeness and challenge results as non-blocking research signals.
A turn may diverge, deepen, challenge or synthesize without forcing every
question through a fixed-seat pipeline.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from equipment_deep_research.deep_runtime.commands import (
    is_card_confirmation,
    parse_slash_command,
)

_RESEARCH_READY_FIELDS = (
    "equipment_form",
    "operational_mechanism",
)

_RESEARCH_READY_EFFECT_FIELDS = (
    "winning_angle",
    "changed_assumption",
    "decisive_target",
    "direct_damage_mechanism",
    "mission_kill_criterion",
    "direct_military_effects",
    "disruptive_difference",
)

ALLOWED_TOOLS: tuple[str, ...] = (
    "help",
    "inspect_memory",
    "deepen",
    "diverge",
    "challenge",
    "synthesize",
    "research_council",
    "author_s6",
)

_REOPEN_MARKERS = (
    "推翻",
    "重开",
    "重新发散",
    "再发散",
    "另起",
    "换方向",
    "换一条",
    "换个方向",
    "换个构型",
    "新候选",
    "三席",
    "全部重来",
    "重开议事",
    "重新提案",
    "不要这个方向",
    "另选方向",
)

_INTENT_TO_TOOL = {
    "deepen": "deepen",
    "followup": "deepen",
    "revise": "deepen",
    "close": "deepen",
    "clarify": "deepen",
    "reopen_council": "research_council",
    "reopen": "research_council",
    "council": "research_council",
    "diverge": "diverge",
    "overturn": "research_council",
    "challenge": "challenge",
    "stress_test": "challenge",
    "red_team": "challenge",
    "synthesize": "synthesize",
    "synthesis": "synthesize",
    "author": "author_s6",
    "card": "author_s6",
    "s6": "author_s6",
    "memory": "inspect_memory",
    "inspect_memory": "inspect_memory",
    "help": "help",
}


@dataclass(frozen=True, slots=True)
class InboundTurn:
    content: str
    command: str | None
    args: str
    authoring_requested: bool
    card_intent: bool
    working_memory: dict[str, Any]
    has_closed_stable_direction: bool
    has_candidate_directions: bool


def working_memory_from_payload(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    source = payload if isinstance(payload, Mapping) else {}
    parent = source.get("deep_parent_context")
    parent = parent if isinstance(parent, Mapping) else {}
    memory = parent.get("working_memory")
    if not isinstance(memory, Mapping) or not memory:
        memory = source.get("working_memory")
    return dict(memory) if isinstance(memory, Mapping) else {}


def _text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _candidate_rows(memory: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    if not isinstance(memory, Mapping):
        return []
    raw = memory.get("candidate_directions")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []
    return [item for item in raw if isinstance(item, Mapping)]


def has_candidate_directions(memory: Mapping[str, Any] | None) -> bool:
    return any(_text(item.get("name")) for item in _candidate_rows(memory))


def has_closed_stable_direction(memory: Mapping[str, Any] | None) -> bool:
    """Return whether a coherent direction can be fixed as an S6 card.

    This is a structural readiness check, not an evidence or publication gate.
    Missing dimensions remain visible as research gaps for later turns.
    """

    for item in _candidate_rows(memory):
        if not item.get("stable"):
            continue
        if not _text(item.get("name")):
            continue
        if all(_text(item.get(field)) for field in _RESEARCH_READY_FIELDS) and any(
            _text(item.get(field)) for field in _RESEARCH_READY_EFFECT_FIELDS
        ):
            return True
    return False


def wants_reopen_council(content: Any) -> bool:
    text = _text(content)
    if not text:
        return False
    return any(marker in text for marker in _REOPEN_MARKERS)


def conductor_may_choose_tool(inbound: InboundTurn) -> bool:
    """Whether a model decision can change the heuristic tool stage."""

    return bool(
        not inbound.command
        and not inbound.card_intent
        and inbound.has_candidate_directions
    )


def inbound_from_payload(payload: Mapping[str, Any] | None) -> InboundTurn:
    source = payload if isinstance(payload, Mapping) else {}
    content = _text(source.get("question") or source.get("topic"))
    parsed = parse_slash_command(content)
    memory = working_memory_from_payload(source)
    closed = has_closed_stable_direction(memory)
    # Missing transport metadata must never be interpreted as permission to
    # author an S6 card.  Only an explicit API flag or the governed /card
    # command can open the authoring path.
    authoring_requested = bool(source.get("authoring_requested", False))
    if parsed.name == "card":
        authoring_requested = True
    elif parsed.name in {"memory", "help", "diverge", "challenge", "synthesize"}:
        authoring_requested = False
    card_intent = (
        parsed.name == "card"
        or is_card_confirmation(content)
        or (authoring_requested and closed)
    )
    return InboundTurn(
        content=content,
        command=parsed.name,
        args=parsed.args,
        authoring_requested=authoring_requested,
        card_intent=card_intent,
        working_memory=memory,
        has_closed_stable_direction=closed,
        has_candidate_directions=has_candidate_directions(memory),
    )


def plan_turn(inbound: InboundTurn) -> list[str]:
    """Heuristic tool sequence used when the conductor is skipped or fails."""

    if inbound.command == "help":
        return ["help"]
    if inbound.command == "memory":
        return ["inspect_memory"]
    if inbound.command == "diverge":
        return ["diverge"]
    if inbound.command == "challenge":
        return ["challenge"] if inbound.has_candidate_directions else ["research_council"]
    if inbound.command == "synthesize":
        return ["synthesize"] if inbound.has_candidate_directions else ["research_council"]
    if inbound.card_intent and inbound.has_closed_stable_direction:
        return ["inspect_memory", "author_s6"]
    if inbound.card_intent:
        return ["research_council"]
    if inbound.has_candidate_directions and wants_reopen_council(inbound.content):
        return ["research_council"]
    if inbound.has_candidate_directions:
        return ["deepen"]
    return ["research_council"]


def sanitize_plan(tools: Sequence[Any] | None, inbound: InboundTurn) -> list[str]:
    """Keep model-chosen tools inside the equipment-research allowlist."""

    ordered: list[str] = []
    for item in tools or ():
        name = _text(item)
        if name in ALLOWED_TOOLS and name not in ordered:
            ordered.append(name)
    if inbound.command == "help":
        return ["help"]
    if inbound.command == "memory":
        return ["inspect_memory"]
    if inbound.command == "diverge":
        return ["diverge"]
    if inbound.command == "challenge":
        return ["challenge"] if inbound.has_candidate_directions else ["research_council"]
    if inbound.command == "synthesize":
        return ["synthesize"] if inbound.has_candidate_directions else ["research_council"]
    if inbound.card_intent and inbound.has_closed_stable_direction:
        return ["inspect_memory", "author_s6"]
    if inbound.card_intent:
        return ["research_council"]
    if "help" in ordered and inbound.command != "help":
        ordered = [name for name in ordered if name != "help"]
    if "author_s6" in ordered and not (
        inbound.card_intent and inbound.has_closed_stable_direction
    ):
        ordered = [name for name in ordered if name != "author_s6"]
        if not any(
            name in ordered
            for name in ("deepen", "diverge", "challenge", "synthesize", "research_council")
        ):
            ordered.append(
                "deepen" if inbound.has_candidate_directions else "research_council"
            )
    primary_actions = [
        name
        for name in ("research_council", "diverge", "deepen")
        if name in ordered
    ]
    if len(primary_actions) > 1:
        if inbound.has_candidate_directions and not wants_reopen_council(
            inbound.content
        ):
            preference = next(
                (
                    name
                    for name in ("deepen", "diverge")
                    if name in ordered
                ),
                "deepen",
            )
        else:
            preference = "diverge" if "diverge" in ordered else "research_council"
        ordered = [
            name
            for name in ordered
            if name not in primary_actions or name == preference
        ]
    if any(
        name in ordered for name in ("deepen", "challenge", "synthesize")
    ) and not inbound.has_candidate_directions:
        ordered = [
            "research_council"
            if name in {"deepen", "challenge", "synthesize"}
            else name
            for name in ordered
        ]
        ordered = list(dict.fromkeys(ordered))
    # One turn may challenge and then synthesize, matching nanobot's
    # observation-aware tool loop without opening an unbounded workflow.
    research_actions = {
        "research_council",
        "diverge",
        "deepen",
        "challenge",
        "synthesize",
    }
    research_count = 0
    bounded: list[str] = []
    for name in ordered:
        if name in research_actions:
            research_count += 1
            if research_count > 2:
                continue
        bounded.append(name)
    ordered = bounded
    if not ordered:
        return plan_turn(inbound)
    return ordered


def sanitize_next_action(
    action: Any,
    inbound: InboundTurn,
    completed_tools: Sequence[str] = (),
    *,
    has_observed_candidates: bool = False,
) -> str | None:
    """Return one allowed action while preserving deterministic command gates."""

    completed = set(completed_tools)
    research_actions = {
        "research_council",
        "diverge",
        "deepen",
        "challenge",
        "synthesize",
    }
    completed_research_actions = sum(
        1 for name in completed_tools if name in research_actions
    )
    forced: list[str] = []
    if inbound.command == "help":
        forced = ["help"]
    elif inbound.command == "memory":
        forced = ["inspect_memory"]
    elif inbound.command == "diverge":
        forced = ["diverge"]
    elif inbound.command == "challenge":
        forced = ["challenge"] if inbound.has_candidate_directions else ["research_council"]
    elif inbound.command == "synthesize":
        forced = ["synthesize"] if inbound.has_candidate_directions else ["research_council"]
    elif inbound.card_intent and inbound.has_closed_stable_direction:
        forced = ["inspect_memory", "author_s6"]
    elif inbound.card_intent:
        forced = ["research_council"]
    if forced:
        pending = next((name for name in forced if name not in completed), None)
        if pending:
            return pending
        # Explicit research commands determine the first action. A tool may
        # request one observation-grounded research continuation, but never
        # S6 authoring or an unbounded chain.
        if (
            inbound.command not in {"diverge", "challenge", "synthesize"}
            or not has_observed_candidates
            or completed_research_actions >= 2
        ):
            return None
        name = tool_from_intent(action) or _text(action)
        if name in research_actions and name not in completed:
            return name
        return None

    name = tool_from_intent(action) or _text(action)
    if not name or name not in ALLOWED_TOOLS:
        return None
    if name in research_actions and completed_research_actions >= 2:
        return None
    if (
        has_observed_candidates
        and name in {"deepen", "challenge", "synthesize"}
        and name not in completed
    ):
        return name
    for candidate in sanitize_plan([name], inbound):
        if candidate not in completed:
            return candidate
    return None


def intent_from_plan(plan: Sequence[str]) -> str:
    if "author_s6" in plan:
        return "author"
    if "research_council" in plan:
        return "reopen_council"
    if "diverge" in plan:
        return "diverge"
    if "challenge" in plan:
        return "challenge"
    if "synthesize" in plan:
        return "synthesize"
    if "deepen" in plan:
        return "deepen"
    if "inspect_memory" in plan:
        return "memory"
    if "help" in plan:
        return "help"
    return "deepen"


def tool_from_intent(intent: Any) -> str | None:
    return _INTENT_TO_TOOL.get(_text(intent).lower())


def preview_turn_plan(
    *,
    content: str,
    authoring_requested: bool,
    working_memory: Mapping[str, Any] | None = None,
    defer_model_choice: bool = False,
) -> list[str]:
    """Return a deterministic preview, or defer when the conductor can override it."""

    payload = {
        "question": content,
        "authoring_requested": authoring_requested,
        "working_memory": dict(working_memory)
        if isinstance(working_memory, Mapping)
        else {},
    }
    inbound = inbound_from_payload(payload)
    if defer_model_choice and conductor_may_choose_tool(inbound):
        return []
    return plan_turn(inbound)
