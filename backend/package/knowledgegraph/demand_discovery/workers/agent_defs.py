"""Markdown agent definition discovery.

The frontmatter parser intentionally supports only a flat subset:
``key: value`` lines, comma-separated ``tools``, and inline JSON ``budget``.
This keeps Phase 2 dependency-free while staying compatible with a future YAML
parser.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from knowledgegraph.demand_discovery.harness.budget import RunBudget


@dataclass(frozen=True)
class AgentDef:
    name: str
    description: str
    tools: list[str]
    model: str
    budget: RunBudget
    system_prompt: str
    source_path: Path


def default_agent_dir() -> Path:
    return Path(__file__).resolve().parent / "agents"


def discover_agents(root: str | Path | None = None) -> dict[str, AgentDef]:
    directory = Path(root) if root is not None else default_agent_dir()
    agents: dict[str, AgentDef] = {}
    if not directory.exists():
        return agents
    for path in sorted(directory.glob("*.md")):
        try:
            agent = parse_agent_def(path.read_text(encoding="utf-8"), source_path=path)
        except ValueError:
            continue
        agents[agent.name] = agent
    return agents


def parse_agent_def(text: str, *, source_path: Path) -> AgentDef:
    metadata, body = _split_frontmatter(text)
    name = metadata.get("name", "").strip()
    if not name:
        raise ValueError(f"agent definition missing name: {source_path}")
    tools = [
        item.strip()
        for item in metadata.get("tools", "").split(",")
        if item.strip()
    ]
    budget_data = json.loads(metadata.get("budget", "{}") or "{}")
    if not isinstance(budget_data, dict):
        raise ValueError(f"budget must be object: {source_path}")
    return AgentDef(
        name=name,
        description=metadata.get("description", "").strip(),
        tools=tools,
        model=metadata.get("model", "default").strip() or "default",
        budget=RunBudget(
            max_tokens=_optional_int(budget_data.get("max_tokens")),
            max_tool_calls=_optional_int(budget_data.get("max_tool_calls")),
            max_wall_clock_ms=_optional_int(budget_data.get("max_wall_clock_ms")),
        ),
        system_prompt=body.strip(),
        source_path=source_path,
    )


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("agent definition missing frontmatter")
    end = -1
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end = index
            break
    if end < 0:
        raise ValueError("agent definition frontmatter not closed")
    metadata: dict[str, str] = {}
    for raw_line in lines[1:end]:
        if not raw_line.strip():
            continue
        if ":" not in raw_line:
            raise ValueError(f"invalid frontmatter line: {raw_line}")
        key, value = raw_line.split(":", 1)
        metadata[key.strip()] = value.strip()
    return metadata, "\n".join(lines[end + 1 :])


def _optional_int(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip():
        return int(value)
    return None
