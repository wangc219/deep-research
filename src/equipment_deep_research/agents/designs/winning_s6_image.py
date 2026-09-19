"""S6 design contract loaded from the Markdown prompt resource.

The orchestration layer imports these names for compatibility with the legacy
winning path, but the prose is owned by ``prompts/dynamic_winning/S6.md``.
"""

from equipment_deep_research.agents.dynamic_prompt_resources import (
    load_dynamic_winning_prompt,
)

from .base import AgentDesignSpec


def _s6_prompt(section: str = "system") -> str:
    return load_dynamic_winning_prompt("S6", section=section)


# Compatibility names consumed by the legacy winning coordinator. Each value
# is injected from S6.md; no S6 authoring prose is embedded in Python.
INNOVATIVE_CAPABILITY_IMAGE_GUIDANCE = _s6_prompt()
CAPABILITY_PORTRAIT_CONCISION_GUIDANCE = _s6_prompt()
CAPABILITY_OVERVIEW_GUIDANCE = _s6_prompt("S6_1")
TECHNOLOGY_IMPLEMENTATION_GUIDANCE = _s6_prompt("S6_2")
CAPABILITY_CLASSIFICATION_GUIDANCE = _s6_prompt()
OPERATIONAL_FEASIBILITY_GUIDANCE = _s6_prompt("S6_3")
CAPABILITY_EFFECTS_GUIDANCE = _s6_prompt("S6_4")
WINNING_LOGIC_GUIDANCE = _s6_prompt("S6_5")
FRONTLINE_LANGUAGE_GUIDANCE = _s6_prompt()


DESIGN = AgentDesignSpec(
    "winning_s6_image",
    "综合形成具体、可证伪、具有未来对抗价值的装备能力画像。",
    guidance={
        "innovative_capability_image": INNOVATIVE_CAPABILITY_IMAGE_GUIDANCE,
        "capability_portrait_concision": CAPABILITY_PORTRAIT_CONCISION_GUIDANCE,
        "capability_overview": CAPABILITY_OVERVIEW_GUIDANCE,
        "technology_implementation": TECHNOLOGY_IMPLEMENTATION_GUIDANCE,
        "capability_classification": CAPABILITY_CLASSIFICATION_GUIDANCE,
        "operational_feasibility": OPERATIONAL_FEASIBILITY_GUIDANCE,
        "capability_effects": CAPABILITY_EFFECTS_GUIDANCE,
        "winning_logic": WINNING_LOGIC_GUIDANCE,
        "frontline_language": FRONTLINE_LANGUAGE_GUIDANCE,
    },
)
