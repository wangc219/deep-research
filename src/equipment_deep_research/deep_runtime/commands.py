"""Slash-command router for the equipment deep-research conversation.

Adapted from nanobot's CommandRouter: exact commands are handled before the
research council so `/memory` and `/card` can change the closed loop.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from equipment_deep_research.deep_runtime.identity import IDENTITY_NAME

CARD_AUTHORING_CONFIRMATION = (
    "确认将当前已收敛方向形成五栏能力卡。"
    "请保持装备身份、作用机理与直接军事价值一致，不再扩展新的候选方向。"
)

COMMANDS: dict[str, dict[str, str]] = {
    "diverge": {
        "label": "重新发散",
        "detail": "围绕当前问题重新生成正交假设，不要求固定三席或固定裁决流程",
        "question": "请围绕当前问题重新深度发散，优先探索彼此正交且信息增益高的新方向。",
    },
    "challenge": {
        "label": "对抗挑战",
        "detail": "针对已有方向寻找反例、最低成本反制与失效边界，再给出修订",
        "question": "请对当前候选做对抗挑战，寻找反例、最低成本反制和失效边界，并据此修订方向。",
    },
    "synthesize": {
        "label": "综合收敛",
        "detail": "比较已有方向并形成研究前沿，不写 S6 能力卡",
        "question": "请综合比较当前候选，保留差异、冲突和待验证假设，形成下一轮研究前沿。",
    },
    "card": {
        "label": "形成能力卡",
        "detail": "用已收敛方向写 S6 五栏，不再扩展新候选",
        "question": CARD_AUTHORING_CONFIRMATION,
    },
    "memory": {
        "label": "查看决策记忆",
        "detail": "只读当前工作记忆，不重跑三席议事",
        "question": "请展示当前决策记忆中的候选方向、裁决与待追问，不要扩展新候选。",
    },
    "help": {
        "label": "命令说明",
        "detail": "列出定向深研可用命令",
        "question": "列出定向深研可用命令。",
    },
}

_COMMAND_RE = re.compile(r"^/([A-Za-z]+)(?:\s+(.*))?$", re.DOTALL)
_CARD_CONFIRMATION_RE = re.compile(
    r"^(?:我\s*)?(?:明确\s*)?确认将当前已收敛方向形成五栏能力卡"
    r"(?:[。.!！])?"
    r"(?:\s*请保持装备身份、作用机理与直接军事价值一致，"
    r"不再扩展新的候选方向(?:[。.!！])?)?$"
)


@dataclass(frozen=True, slots=True)
class ParsedCommand:
    name: str | None
    args: str
    raw: str

    @property
    def is_command(self) -> bool:
        return bool(self.name)


def parse_slash_command(text: Any) -> ParsedCommand:
    raw = " ".join(str(text or "").split()).strip()
    match = _COMMAND_RE.match(raw)
    if not match:
        return ParsedCommand(name=None, args="", raw=raw)
    name = match.group(1).lower()
    if name not in COMMANDS:
        return ParsedCommand(name=None, args="", raw=raw)
    return ParsedCommand(name=name, args=(match.group(2) or "").strip(), raw=raw)


def is_card_confirmation(text: Any) -> bool:
    content = " ".join(str(text or "").split()).strip()
    if not content:
        return False
    # Authoring is a one-way workflow transition, so accept only a standalone
    # affirmative statement.  A quoted prompt or a negated sentence may contain
    # the complete confirmation text but must remain an ordinary follow-up.
    return _CARD_CONFIRMATION_RE.fullmatch(content) is not None


def command_question(parsed: ParsedCommand) -> str:
    if not parsed.name:
        return parsed.raw
    default = COMMANDS[parsed.name]["question"]
    if parsed.args:
        return f"{default} {parsed.args}".strip()
    return default


def help_visible_summary() -> list[str]:
    lines = [
        f"{IDENTITY_NAME}支持斜杠命令改变本轮研究策略：系统会在并行发散、内部深化、对抗挑战和综合收敛之间按需选择；确认成卡后不再扩展新候选。"
    ]
    for name, spec in COMMANDS.items():
        lines.append(f"/{name}  {spec['label']}：{spec['detail']}")
    return lines
