"""Installable capability boundary for the deep-research conversation runtime.

The core loop only knows how to plan and execute a small set of turn tools.
Research know-how lives here as structured, progressively loaded skills.  A
plugin may contribute skills and MCP server declarations without modifying the
loop itself.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
from copy import copy
from threading import Lock
from types import MappingProxyType
from typing import Any

import yaml

from equipment_deep_research.config.settings import load_settings
from equipment_deep_research.deep_runtime.planner import ALLOWED_TOOLS
from equipment_deep_research.harness.profiles import HarnessCatalog


AGENT_PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
AGENT_PLUGIN_MCP_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"

_PLUGIN_NAME = re.compile(r"^(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
_SKILL_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9_.-]*[a-z0-9])?$")
_SKILL_REFERENCE = re.compile(r"(?<![\w$])\$([A-Za-z0-9_.:-]+)")
_FRONTMATTER = re.compile(r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n?", re.DOTALL)
_MAX_ACTIVE_SKILLS = 6
_MAX_PLUGIN_FILES = 512
_MAX_PLUGIN_DIRECTORIES = 256
_MAX_PLUGIN_FILE_BYTES = 2 * 1024 * 1024
_MAX_PLUGIN_TOTAL_BYTES = 16 * 1024 * 1024
_MAX_PLUGIN_DEPTH = 12
_PLUGIN_STATE_LOCK = Lock()

# The dialogue loop exposes a small set of coarse research actions. The skills below remain
# procedural research knowledge: their declared tools describe method usage and
# never grant execution permission; this map says where each procedure applies.
_DEFAULT_SKILLS_BY_TURN_TOOL: dict[str, tuple[str, ...]] = {
    "research_council": (
        "counterfactual_triz_innovation",
        "ooda_vulnerability_analysis",
        "dotmlpf_capability_mapping",
    ),
    "deepen": (
        "counterfactual_triz_innovation",
        "effect_chain_analysis",
        "equipment_system_gap_assessment",
    ),
    "diverge": (
        "counterfactual_triz_innovation",
        "ooda_vulnerability_analysis",
        "equipment_system_gap_assessment",
    ),
    "challenge": (
        "effect_chain_analysis",
        "ooda_vulnerability_analysis",
        "equipment_system_gap_assessment",
    ),
    "synthesize": (
        "counterfactual_triz_innovation",
        "effect_chain_analysis",
        "dotmlpf_capability_mapping",
    ),
    "author_s6": ("capability_portfolio_synthesis",),
    "inspect_memory": ("codex_structured_handoff_shared",),
}
_DEEP_RECOMMENDED_SKILLS = frozenset(
    skill_id
    for skill_ids in _DEFAULT_SKILLS_BY_TURN_TOOL.values()
    for skill_id in skill_ids
)


def _text(value: object, limit: int = 1200) -> str:
    return " ".join(str(value or "").split()).strip()[: max(0, int(limit))]


def _string_list(value: object, *, limit: int, item_limit: int = 240) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    items: list[str] = []
    for item in value:
        text = _text(item, item_limit)
        if text and text not in items:
            items.append(text)
        if len(items) >= limit:
            break
    return tuple(items)


def _project_root() -> Path:
    return load_settings().paths.root


@dataclass(frozen=True, slots=True)
class ProceduralSkill:
    skill_id: str
    description: str
    triggers: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    steps: tuple[str, ...]
    required_artifacts: tuple[str, ...]
    quality_gates: tuple[str, ...]
    stop_conditions: tuple[str, ...]
    applies_to: tuple[str, ...] = ()
    source: str = "builtin"
    plugin_id: str = ""
    instructions: str = ""
    resources: tuple[str, ...] = ()
    required_bins: tuple[str, ...] = ()
    required_env: tuple[str, ...] = ()
    missing_requirements: tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        return not self.missing_requirements

    def runtime_payload(self) -> dict[str, Any]:
        """Return the bounded procedure injected only when this skill is active."""

        return {
            "skill_id": self.skill_id,
            "description": self.description,
            "allowed_tools": list(self.allowed_tools),
            "steps": list(self.steps),
            "required_artifacts": list(self.required_artifacts),
            "quality_gates": list(self.quality_gates),
            "stop_conditions": list(self.stop_conditions),
            **({"instructions": self.instructions} if self.instructions else {}),
            **({"resources": list(self.resources)} if self.resources else {}),
            "source": self.source,
            **({"plugin_id": self.plugin_id} if self.plugin_id else {}),
        }

    def public_payload(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "description": self.description,
            "triggers": list(self.triggers),
            "allowed_tools": list(self.allowed_tools),
            "steps": list(self.steps),
            "required_artifacts": list(self.required_artifacts),
            "quality_gates": list(self.quality_gates),
            "stop_conditions": list(self.stop_conditions),
            "applies_to": list(self.applies_to),
            "source": self.source,
            "plugin_id": self.plugin_id,
            "recommended": self.skill_id in _DEEP_RECOMMENDED_SKILLS,
            "available": self.available,
            "missing_requirements": list(self.missing_requirements),
            "resources": list(self.resources),
            "has_instructions": bool(self.instructions),
        }


@dataclass(frozen=True, slots=True)
class MCPDeclaration:
    server_id: str
    transport: str
    plugin_id: str

    def public_payload(self) -> dict[str, str]:
        return {
            "server_id": self.server_id,
            "transport": self.transport,
            "plugin_id": self.plugin_id,
            "execution_status": "declaration_only",
        }


@dataclass(frozen=True, slots=True)
class DeepPlugin:
    plugin_id: str
    display_name: str
    description: str
    category: str
    permissions: tuple[str, ...]
    root: Path = field(repr=False)
    fingerprint: str = field(repr=False)
    default_enabled: bool = False
    enabled: bool = False
    skills: tuple[ProceduralSkill, ...] = ()
    mcp_servers: tuple[MCPDeclaration, ...] = ()
    source: str = "deployment"

    def public_payload(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "display_name": self.display_name,
            "description": self.description,
            "category": self.category,
            "permissions": list(self.permissions),
            "enabled": self.enabled,
            "source": self.source,
            "skill_ids": [item.skill_id for item in self.skills],
            "mcp_servers": [item.public_payload() for item in self.mcp_servers],
        }


@dataclass(frozen=True, slots=True)
class _PackageSnapshot:
    """One bounded package view used for both authorization and parsing."""

    fingerprint: str
    files: Mapping[str, bytes] = field(repr=False)
    directories: tuple[str, ...] = ()


class DeepCapabilityRegistry:
    """Discover built-in procedures and explicitly installed plugin packages."""

    def __init__(
        self,
        *,
        harness_path: Path,
        plugins_root: Path,
        state_path: Path,
        plugin_state: Mapping[str, Any] | None = None,
    ) -> None:
        self.harness_path = harness_path.expanduser().resolve()
        self.plugins_root = plugins_root.expanduser().resolve()
        self.state_path = state_path.expanduser().absolute()
        self._plugin_state = dict(plugin_state) if plugin_state is not None else self._read_plugin_state()
        self.plugins = self._discover_plugins()
        self.skills = self._load_builtin_skills()
        for plugin in self.plugins:
            if not plugin.enabled:
                continue
            for skill in plugin.skills:
                if skill.available:
                    self.skills.setdefault(skill.skill_id, skill)

    def with_workspace(self, workspace: Any) -> "DeepCapabilityRegistry":
        """Build an equipment-local snapshot without changing deployment state."""

        result = copy(self)
        result.skills = dict(self.skills)
        if workspace.plugins_dir.is_symlink():
            raise ValueError("workspace plugin root must not be a symlink")
        config_snapshot = self._package_snapshot(workspace.config_dir)
        def read_config(name: str) -> Mapping[str, Any]:
            try:
                raw = json.loads((config_snapshot.files.get(name, b"{}") if config_snapshot else b"{}").decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError, RecursionError):
                return {}
            return raw if isinstance(raw, Mapping) else {}

        saved = read_config("plugins.json")
        saved = saved.get("plugins", saved)
        # State is stored outside plugin packages so enabling a package never
        # changes the fingerprint that authorizes its contents.
        local = type(self)(
            harness_path=self.harness_path,
            plugins_root=workspace.plugins_dir,
            state_path=workspace.config_dir / "plugins.json",
            plugin_state=saved if isinstance(saved, Mapping) else {},
        )
        global_ids = {plugin.plugin_id for plugin in self.plugins}
        local_plugins = tuple(replace(plugin, source="workspace") for plugin in local.plugins if plugin.plugin_id not in global_ids)
        result.plugins = (*self.plugins, *local_plugins)
        for plugin in local_plugins:
            if plugin.enabled:
                for skill in plugin.skills:
                    if skill.available:
                        result.skills.setdefault(skill.skill_id, skill)

        snapshot = self._package_snapshot(workspace.skills_dir)
        if snapshot is not None:
            for relative, content in sorted(snapshot.files.items()):
                parts = PurePosixPath(relative).parts
                if len(parts) != 2 or parts[1] != "SKILL.md":
                    continue
                row = self._markdown_skill(content, parts[0])
                if row is None or row.get("name") != parts[0]:
                    continue
                skill = self._plugin_skill("workspace", row, snapshot)
                if skill is not None and skill.available:
                    result.skills[skill.skill_id] = replace(skill, source="workspace", plugin_id="")

        result.workspace_config = {}
        if config_snapshot is not None:
            raw = read_config("runtime.json")
            if isinstance(raw, Mapping):
                # Only research preferences are configurable. Identity, S6,
                # provider, tools and executable MCP mounting remain host-owned.
                for key in ("active_skill_ids", "disabled_skill_ids"):
                    result.workspace_config[key] = list(_string_list(raw.get(key), limit=64, item_limit=140))
                budget = raw.get("deep_runtime_budget")
                if isinstance(budget, Mapping):
                    result.workspace_config["deep_runtime_budget"] = {
                        key: max(0, min(value, 12))
                        for key in ("max_turns", "max_tool_calls")
                        if isinstance(value := budget.get(key), int) and not isinstance(value, bool)
                    }
        for skill_id in result.workspace_config.get("disabled_skill_ids", []):
            result.skills.pop(skill_id, None)
        return result

    @classmethod
    def load_default(cls) -> "DeepCapabilityRegistry":
        root = _project_root()
        config_root = Path(
            os.environ.get(
                "EQUIPMENT_DR_CONFIG_ROOT",
                root / "configs" / "equipment_deep_research",
            )
        )
        plugins_root = Path(
            os.environ.get(
                "EQUIPMENT_DR_DEEP_PLUGIN_ROOT",
                config_root / "plugins",
            )
        )
        state_path = Path(
            os.environ.get(
                "EQUIPMENT_DR_DEEP_PLUGIN_STATE",
                root / "outputs" / "runtime" / "deep-plugins.json",
            )
        )
        return cls(
            harness_path=config_root / "harness.yaml",
            plugins_root=plugins_root,
            state_path=state_path,
        )

    def _load_builtin_skills(self) -> dict[str, ProceduralSkill]:
        if not self.harness_path.is_file():
            return {}
        catalog = HarnessCatalog.load(self.harness_path)
        skills: dict[str, ProceduralSkill] = {}
        for skill in catalog.skills.values():
            description = (
                f"按顺序执行：{'；'.join(skill.steps[:3])}"
                if skill.steps
                else skill.skill_id
            )
            applies_to = tuple(
                tool_name
                for tool_name, skill_ids in _DEFAULT_SKILLS_BY_TURN_TOOL.items()
                if skill.skill_id in skill_ids
            )
            skills[skill.skill_id] = ProceduralSkill(
                skill_id=skill.skill_id,
                description=description,
                triggers=tuple(skill.triggers),
                allowed_tools=tuple(skill.allowed_tools),
                steps=tuple(skill.steps),
                required_artifacts=tuple(skill.required_artifacts),
                quality_gates=tuple(skill.quality_gates),
                stop_conditions=tuple(skill.stop_conditions),
                applies_to=applies_to,
            )
        return skills

    def _read_plugin_state(self) -> dict[str, dict[str, Any]]:
        try:
            descriptor = os.open(self.state_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
            with os.fdopen(descriptor, "rb") as handle:
                if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                    return {}
                content = handle.read(256 * 1024 + 1)
            if len(content) > 256 * 1024:
                return {}
            raw = json.loads(content.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, Mapping):
            return {}
        plugins = raw.get("plugins", raw)
        if not isinstance(plugins, Mapping):
            return {}
        return {
            str(name): dict(value)
            for name, value in plugins.items()
            if isinstance(value, Mapping)
        }

    def _discover_plugins(self) -> tuple[DeepPlugin, ...]:
        try:
            root = self.plugins_root.resolve(strict=True)
        except OSError:
            return ()
        if not root.is_dir():
            return ()
        plugins: list[DeepPlugin] = []
        seen: set[str] = set()
        for candidate in sorted(root.iterdir(), key=lambda item: item.name):
            if candidate.is_symlink():
                continue
            plugin_root = self._contained(candidate, root, directory=True)
            if plugin_root is None:
                continue
            plugin = self._load_plugin(plugin_root)
            if plugin is None or plugin.plugin_id in seen:
                continue
            seen.add(plugin.plugin_id)
            plugins.append(plugin)
        return tuple(plugins)

    def _load_plugin(self, root: Path) -> DeepPlugin | None:
        snapshot = self._package_snapshot(root)
        if snapshot is None:
            return None
        try:
            payload = json.loads(snapshot.files["plugin.json"].decode("utf-8"))
        except (KeyError, UnicodeError, json.JSONDecodeError, RecursionError):
            return None
        if not isinstance(payload, Mapping) or payload.get("$schema") != AGENT_PLUGIN_SCHEMA:
            return None
        plugin_id = _text(payload.get("name"), 64)
        if not plugin_id or _PLUGIN_NAME.fullmatch(plugin_id) is None:
            return None
        fingerprint = snapshot.fingerprint
        extensions = payload.get("extensions")
        extensions = extensions if isinstance(extensions, Mapping) else {}
        extension = extensions.get("dev.equipment-deep-research")
        extension = extension if isinstance(extension, Mapping) else {}
        default_enabled = bool(extension.get("defaultEnabled", False))
        saved = self._plugin_state.get(plugin_id)
        if isinstance(saved, Mapping):
            enabled = (
                bool(saved.get("enabled"))
                and saved.get("fingerprint") == fingerprint
                and saved.get("root") == str(root)
            )
        else:
            # Discovered packages are inert until an operator explicitly
            # enables the exact installed root and content fingerprint.
            enabled = False
        skills = self._plugin_skills(plugin_id, snapshot)
        servers = self._plugin_mcp(plugin_id, snapshot)
        if enabled:
            # Authorization and parsing use the first immutable snapshot. A
            # second bounded read makes a package changed during loading fail
            # closed for this registry instance.
            verified = self._package_snapshot(root)
            if verified is None or verified.fingerprint != fingerprint:
                enabled = False
        return DeepPlugin(
            plugin_id=plugin_id,
            display_name=_text(extension.get("displayName") or plugin_id, 120),
            description=_text(payload.get("description"), 600),
            category=_text(extension.get("category") or "研究能力", 80),
            permissions=_string_list(extension.get("permissions"), limit=16, item_limit=120),
            root=root,
            fingerprint=fingerprint,
            default_enabled=default_enabled,
            enabled=enabled,
            skills=skills,
            mcp_servers=servers,
        )

    def _plugin_skills(
        self, plugin_id: str, snapshot: _PackageSnapshot
    ) -> tuple[ProceduralSkill, ...]:
        rows: list[Mapping[str, Any]] = []
        catalog = snapshot.files.get("skills.yaml")
        if catalog is not None:
            try:
                payload = yaml.safe_load(catalog.decode("utf-8")) or {}
            except (UnicodeError, yaml.YAMLError, RecursionError):
                payload = {}
            raw_rows = payload.get("skills", []) if isinstance(payload, Mapping) else []
            if isinstance(raw_rows, Sequence) and not isinstance(raw_rows, (str, bytes)):
                rows.extend(item for item in raw_rows if isinstance(item, Mapping))

        for relative, content in sorted(snapshot.files.items()):
            parts = PurePosixPath(relative).parts
            if len(parts) != 3 or parts[0] != "skills" or parts[2] != "SKILL.md":
                continue
            parsed = self._markdown_skill(content, "/".join(parts[:2]))
            if parsed is not None:
                rows.append(parsed)

        skills: list[ProceduralSkill] = []
        seen: set[str] = set()
        for row in rows:
            skill = self._plugin_skill(plugin_id, row, snapshot)
            if skill is None or skill.skill_id in seen:
                continue
            seen.add(skill.skill_id)
            skills.append(skill)
        return tuple(skills)

    @staticmethod
    def _markdown_skill(raw: bytes, skill_root: str) -> Mapping[str, Any] | None:
        try:
            content = raw.decode("utf-8")
        except UnicodeError:
            return None
        match = _FRONTMATTER.match(content)
        if match is None:
            return None
        try:
            metadata = yaml.safe_load(match.group(1)) or {}
        except (yaml.YAMLError, RecursionError):
            return None
        if not isinstance(metadata, Mapping):
            return None
        procedure = metadata.get("procedure")
        procedure = procedure if isinstance(procedure, Mapping) else {}
        return {
            **dict(metadata),
            **dict(procedure),
            "_instructions": content[match.end() :].strip()[:8000],
            "_skill_root": skill_root,
        }

    def _plugin_skill(
        self,
        plugin_id: str,
        row: Mapping[str, Any],
        snapshot: _PackageSnapshot,
    ) -> ProceduralSkill | None:
        local_name = _text(row.get("skill_id") or row.get("name"), 64).lower()
        if not local_name or _SKILL_NAME.fullmatch(local_name) is None:
            return None
        steps = _string_list(row.get("steps"), limit=16, item_limit=500)
        artifacts = _string_list(row.get("required_artifacts"), limit=16, item_limit=120)
        gates = _string_list(row.get("quality_gates"), limit=16, item_limit=500)
        stops = _string_list(row.get("stop_conditions"), limit=12, item_limit=500)
        # A plugin skill is executable know-how only when it declares a real
        # procedure.  Free-form markdown without these contracts is ignored.
        if not steps or not artifacts or not gates or not stops:
            return None
        requirements = self._skill_requirements(row)
        required_bins = _string_list(requirements.get("bins"), limit=16, item_limit=80)
        required_env = _string_list(requirements.get("env"), limit=16, item_limit=120)
        missing = tuple(
            [f"CLI:{name}" for name in required_bins if shutil.which(name) is None]
            + [f"ENV:{name}" for name in required_env if not os.environ.get(name)]
        )
        skill_root = ""
        configured_root = _text(row.get("_skill_root"), 1200)
        if configured_root:
            candidate_root = self._snapshot_directory(configured_root, snapshot)
            if candidate_root is None:
                return None
            skill_root = candidate_root
        resources = self._skill_resources(skill_root, snapshot)
        return ProceduralSkill(
            skill_id=f"{plugin_id}:{local_name}",
            description=_text(row.get("description") or steps[0], 600),
            triggers=_string_list(row.get("triggers"), limit=24, item_limit=80),
            allowed_tools=_string_list(row.get("allowed_tools"), limit=32, item_limit=120),
            steps=steps,
            required_artifacts=artifacts,
            quality_gates=gates,
            stop_conditions=stops,
            applies_to=_string_list(row.get("applies_to"), limit=5, item_limit=40),
            source="plugin",
            plugin_id=plugin_id,
            instructions=str(row.get("_instructions") or "").strip()[:8000],
            resources=resources,
            required_bins=required_bins,
            required_env=required_env,
            missing_requirements=missing,
        )

    @staticmethod
    def _skill_requirements(row: Mapping[str, Any]) -> Mapping[str, Any]:
        direct = row.get("requires")
        if isinstance(direct, Mapping):
            return direct
        metadata = row.get("metadata")
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except (TypeError, json.JSONDecodeError, RecursionError):
                metadata = {}
        if not isinstance(metadata, Mapping):
            return {}
        nested = metadata.get("nanobot", metadata.get("openclaw", metadata))
        if not isinstance(nested, Mapping):
            return {}
        requires = nested.get("requires")
        return requires if isinstance(requires, Mapping) else {}

    @staticmethod
    def _snapshot_directory(
        value: str, snapshot: _PackageSnapshot
    ) -> str | None:
        raw = value.replace("\\", "/")
        path = PurePosixPath(raw)
        if not raw or path.is_absolute() or ".." in path.parts:
            return None
        normalized = raw.strip("/")
        path = PurePosixPath(normalized)
        if not normalized or any(":" in part for part in path.parts):
            return None
        relative = path.as_posix()
        return relative if relative in snapshot.directories else None

    def _skill_resources(
        self, skill_root: str, snapshot: _PackageSnapshot
    ) -> tuple[str, ...]:
        """Index package resources without exposing or executing their contents."""

        resources: list[str] = []
        root_prefix = f"{skill_root}/" if skill_root else ""
        for directory_name in ("scripts", "references", "assets"):
            prefix = f"{root_prefix}{directory_name}/"
            for relative in sorted(snapshot.files):
                if not relative.startswith(prefix):
                    continue
                resource = relative[len(root_prefix) :]
                if resource not in resources:
                    resources.append(resource)
                if len(resources) >= 32:
                    return tuple(resources)
        return tuple(resources)

    def _plugin_mcp(
        self, plugin_id: str, snapshot: _PackageSnapshot
    ) -> tuple[MCPDeclaration, ...]:
        raw_payload = snapshot.files.get("mcp.json")
        if raw_payload is None:
            return ()
        try:
            payload = json.loads(raw_payload.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError, RecursionError):
            return ()
        if not isinstance(payload, Mapping):
            return ()
        servers = payload.get("mcpServers")
        if payload.get("$schema") != AGENT_PLUGIN_MCP_SCHEMA or not isinstance(servers, Mapping):
            return ()
        result: list[MCPDeclaration] = []
        for name, raw in servers.items():
            server_id = _text(name, 128)
            if not server_id or not isinstance(raw, Mapping):
                continue
            transport = _text(raw.get("type") or ("http" if raw.get("url") else "stdio"), 24)
            if transport not in {"stdio", "http", "sse"}:
                continue
            result.append(
                MCPDeclaration(
                    server_id=f"{plugin_id}:{server_id}",
                    transport=transport,
                    plugin_id=plugin_id,
                )
            )
        return tuple(result)

    @staticmethod
    def _contained(path: Path, root: Path, *, directory: bool = False) -> Path | None:
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            return None
        if not resolved.is_relative_to(root):
            return None
        if directory and not resolved.is_dir():
            return None
        if not directory and not resolved.is_file():
            return None
        return resolved

    @classmethod
    def _package_snapshot(cls, root: Path) -> _PackageSnapshot | None:
        """Read a package through no-follow descriptors under explicit quotas."""

        files: dict[str, bytes] = {}
        directories: list[str] = []
        total_bytes = 0
        file_count = 0
        directory_count = 0
        entry_count = 0
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        directory_flag = getattr(os, "O_DIRECTORY", 0)

        def _read_file(parent_fd: int, name: str, expected: os.stat_result) -> bytes:
            nonlocal total_bytes, file_count
            file_count += 1
            if file_count > _MAX_PLUGIN_FILES:
                raise OSError("plugin file-count limit exceeded")
            descriptor = os.open(name, os.O_RDONLY | nofollow, dir_fd=parent_fd)
            try:
                before = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(before.st_mode)
                    or before.st_dev != expected.st_dev
                    or before.st_ino != expected.st_ino
                    or before.st_size != expected.st_size
                    or before.st_mtime_ns != expected.st_mtime_ns
                ):
                    raise OSError("plugin entry is not a regular file")
                if before.st_size > _MAX_PLUGIN_FILE_BYTES:
                    raise OSError("plugin file-size limit exceeded")
                chunks: list[bytes] = []
                size = 0
                while True:
                    remaining = _MAX_PLUGIN_FILE_BYTES + 1 - size
                    chunk = os.read(descriptor, min(65536, remaining))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > _MAX_PLUGIN_FILE_BYTES:
                        raise OSError("plugin file-size limit exceeded")
                after = os.fstat(descriptor)
                if (
                    before.st_dev != after.st_dev
                    or before.st_ino != after.st_ino
                    or before.st_size != after.st_size
                    or before.st_mtime_ns != after.st_mtime_ns
                ):
                    raise OSError("plugin file changed while being read")
                total_bytes += size
                if total_bytes > _MAX_PLUGIN_TOTAL_BYTES:
                    raise OSError("plugin total-size limit exceeded")
                return b"".join(chunks)
            finally:
                os.close(descriptor)

        def _walk(directory_fd: int, prefix: str, depth: int) -> None:
            nonlocal directory_count, entry_count
            if depth > _MAX_PLUGIN_DEPTH:
                raise OSError("plugin directory-depth limit exceeded")
            with os.scandir(directory_fd) as iterator:
                names: list[str] = []
                for entry in iterator:
                    entry_count += 1
                    if entry_count > _MAX_PLUGIN_FILES + _MAX_PLUGIN_DIRECTORIES:
                        raise OSError("plugin entry-count limit exceeded")
                    names.append(entry.name)
                names.sort()
            for name in names:
                if not name or name in {".", ".."} or "/" in name or "\\" in name:
                    raise OSError("invalid plugin entry name")
                try:
                    name.encode("utf-8")
                except UnicodeEncodeError as exc:
                    raise OSError("plugin entry name is not UTF-8 encodable") from exc
                relative = f"{prefix}/{name}" if prefix else name
                entry_stat = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                if stat.S_ISLNK(entry_stat.st_mode):
                    raise OSError("plugin symlinks are not allowed")
                if stat.S_ISREG(entry_stat.st_mode):
                    files[relative] = _read_file(directory_fd, name, entry_stat)
                    continue
                if not stat.S_ISDIR(entry_stat.st_mode):
                    raise OSError("unsupported plugin entry type")
                directory_count += 1
                if directory_count > _MAX_PLUGIN_DIRECTORIES:
                    raise OSError("plugin directory-count limit exceeded")
                directories.append(relative)
                child_fd = os.open(
                    name,
                    os.O_RDONLY | directory_flag | nofollow,
                    dir_fd=directory_fd,
                )
                try:
                    child_stat = os.fstat(child_fd)
                    if (
                        not stat.S_ISDIR(child_stat.st_mode)
                        or child_stat.st_dev != entry_stat.st_dev
                        or child_stat.st_ino != entry_stat.st_ino
                    ):
                        raise OSError("plugin directory changed while being opened")
                    _walk(child_fd, relative, depth + 1)
                finally:
                    os.close(child_fd)

        try:
            root_lstat = os.lstat(root)
            if not stat.S_ISDIR(root_lstat.st_mode) or stat.S_ISLNK(root_lstat.st_mode):
                return None
            root_fd = os.open(root, os.O_RDONLY | directory_flag | nofollow)
            try:
                root_stat = os.fstat(root_fd)
                if (
                    not stat.S_ISDIR(root_stat.st_mode)
                    or root_stat.st_dev != root_lstat.st_dev
                    or root_stat.st_ino != root_lstat.st_ino
                ):
                    return None
                _walk(root_fd, "", 1)
            finally:
                os.close(root_fd)
        except (OSError, OverflowError):
            return None

        digest = sha256()
        for relative in sorted((*directories, *files)):
            digest.update(relative.encode("utf-8"))
            if relative in files:
                digest.update(b"\0file\0")
                digest.update(files[relative])
            else:
                digest.update(b"\0dir\0")
            digest.update(b"\0")
        return _PackageSnapshot(
            fingerprint=digest.hexdigest(),
            files=MappingProxyType(dict(files)),
            directories=tuple(sorted(directories)),
        )

    @classmethod
    def _package_fingerprint(cls, root: Path) -> str:
        snapshot = cls._package_snapshot(root)
        return snapshot.fingerprint if snapshot is not None else ""

    def set_plugin_enabled(self, plugin_id: str, enabled: bool) -> DeepPlugin:
        plugin = next((item for item in self.plugins if item.plugin_id == plugin_id), None)
        if plugin is None:
            raise KeyError(plugin_id)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.state_path.with_suffix(f"{self.state_path.suffix}.lock")
        lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0), 0o600)
        with _PLUGIN_STATE_LOCK, os.fdopen(lock_fd, "a+", encoding="utf-8") as lock_handle:
            if not stat.S_ISREG(os.fstat(lock_handle.fileno()).st_mode):
                raise ValueError("plugin state lock must be a regular file")
            try:
                import fcntl

                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            except (ImportError, OSError):
                fcntl = None  # type: ignore[assignment]
            try:
                # Registry instances are short lived, but two API workers can
                # still toggle different plugins from stale snapshots. Re-read
                # while holding the cross-process lock before the atomic write.
                state = dict(self._read_plugin_state())
                state[plugin.plugin_id] = {
                    "enabled": bool(enabled),
                    "fingerprint": plugin.fingerprint,
                    "root": str(plugin.root),
                }
                payload = {
                    "schema_version": "deep-plugin-state-v2",
                    "plugins": state,
                }
                with tempfile.NamedTemporaryFile(
                    "w",
                    encoding="utf-8",
                    dir=self.state_path.parent,
                    prefix=f".{self.state_path.name}.",
                    delete=False,
                ) as handle:
                    json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
                    handle.flush()
                    os.fsync(handle.fileno())
                    temporary = Path(handle.name)
                os.replace(temporary, self.state_path)
                try:
                    directory_fd = os.open(self.state_path.parent, os.O_RDONLY)
                except OSError:
                    directory_fd = -1
                if directory_fd >= 0:
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)
            finally:
                if fcntl is not None:
                    try:
                        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
                    except OSError:
                        pass
        refreshed = type(self)(
            harness_path=self.harness_path,
            plugins_root=self.plugins_root,
            state_path=self.state_path,
        )
        result = next(item for item in refreshed.plugins if item.plugin_id == plugin_id)
        return result

    def requested_skill_ids(self, text: object, requested: Sequence[object] = ()) -> list[str]:
        result: list[str] = []
        for value in requested:
            skill_id = _text(value, 140)
            if skill_id in self.skills and skill_id not in result:
                result.append(skill_id)
        for match in _SKILL_REFERENCE.finditer(str(text or "")):
            skill_id = match.group(1)
            if skill_id in self.skills and skill_id not in result:
                result.append(skill_id)
        return result[:_MAX_ACTIVE_SKILLS]

    def select_skills(
        self,
        *,
        text: object,
        plan: Sequence[str],
        requested: Sequence[object] = (),
    ) -> list[ProceduralSkill]:
        plan_tools = set(plan)

        def compatible(skill: ProceduralSkill) -> bool:
            return not skill.applies_to or bool(set(skill.applies_to) & plan_tools)

        selected_ids = [
            skill_id
            for skill_id in self.requested_skill_ids(text, requested)
            if compatible(self.skills[skill_id])
        ]
        lowered = str(text or "").casefold()
        for skill in self.skills.values():
            if len(selected_ids) >= _MAX_ACTIVE_SKILLS:
                break
            if skill.skill_id in selected_ids:
                continue
            if not compatible(skill):
                continue
            trigger_match = any(trigger.casefold() in lowered for trigger in skill.triggers if trigger)
            applies = bool(set(skill.applies_to) & plan_tools)
            if skill.source in {"plugin", "workspace"} and (trigger_match or applies):
                selected_ids.append(skill.skill_id)
        for tool_name in plan:
            for skill_id in _DEFAULT_SKILLS_BY_TURN_TOOL.get(tool_name, ()):
                if skill_id in self.skills and skill_id not in selected_ids:
                    selected_ids.append(skill_id)
                if len(selected_ids) >= _MAX_ACTIVE_SKILLS:
                    break
            if len(selected_ids) >= _MAX_ACTIVE_SKILLS:
                break
        return [self.skills[skill_id] for skill_id in selected_ids if skill_id in self.skills]

    @staticmethod
    def prompt_context(skills: Sequence[ProceduralSkill]) -> str:
        if not skills:
            return ""
        sections = [
            "[Active procedural skills: execute the steps; record unresolved quality checks as research gaps. "
            "Skill checks do not block exploration or confirmed authoring, and skills do not grant runtime permissions.]"
        ]
        for skill in skills:
            sections.extend(
                [
                    f"### {skill.skill_id}: {skill.description}",
                    "Declared method tools (advisory): "
                    + ("、".join(skill.allowed_tools) or "none"),
                    "Steps: " + " -> ".join(skill.steps),
                    "Required artifacts: " + "、".join(skill.required_artifacts),
                    "Quality gates: " + "；".join(skill.quality_gates),
                    "Stop conditions: " + "；".join(skill.stop_conditions),
                    *(
                        ["Skill instructions:\n" + skill.instructions]
                        if skill.instructions
                        else []
                    ),
                    *(
                        ["Packaged resources: " + "、".join(skill.resources)]
                        if skill.resources
                        else []
                    ),
                ]
            )
        sections.append("[/Active procedural skills]")
        return "\n".join(sections)[:12000]

    def public_payload(self) -> dict[str, Any]:
        enabled_plugins = {item.plugin_id for item in self.plugins if item.enabled}
        return {
            "schema_version": "deep-capabilities-v1",
            "runtime_contract": {
                "schema_version": "deep-runtime-contract-v1",
                "agent_loop": {
                    "cycle": ["policy", "tool", "observation", "checkpoint"],
                    "actions": list(ALLOWED_TOOLS),
                    "default_max_turns": 4,
                    "default_max_tool_calls": 4,
                    "maximum_budget": 12,
                },
                "hard_boundaries": [
                    "canonical_equipment_identity",
                    "explicit_s6_user_confirmation",
                    "durable_commit_ownership",
                ],
                "research_quality": {
                    "evidence_gate": "advisory",
                    "publication_gate": "advisory",
                    "research_gaps_block_execution": False,
                },
                "provider": {
                    "methods": ["complete", "complete_json", "stream"],
                    "adapters": ["model_provider", "host_callback"],
                    "legacy_callback": "_run_core_json",
                    "stream_requires_model_provider": True,
                    "public_snapshot": "allowlist",
                },
                "channel": {
                    "messages": ["InboundMessage", "OutboundMessage"],
                    "bus": "MessageBus",
                    "web_ingress": "job_local_bus_dispatch",
                    "host_dependencies_on_bus": False,
                    "private_result_for_durable_commit": True,
                    "persistent": "optional_host_backend",
                    "durable_backend": "SqlMessageBusStore",
                    "durable_delivery": "lease_with_owner_fencing",
                    "payload_policy": "research_hints_with_host_precedence",
                    "host_owned": [
                        "canonical_identity",
                        "session",
                        "working_memory",
                        "s6_authorization",
                        "workspace",
                    ],
                },
                "subagents": {
                    "activation": "explicit_opt_in",
                    "default_tasks": 2,
                    "maximum_tasks": 4,
                    "maximum_concurrent": 4,
                    "merge_fields": ["finding", "assumptions", "next_probe"],
                    "isolated_context": True,
                    "owns_session_or_tools": False,
                },
                "capabilities": {
                    "workspace_discovery": ["skills", "plugins", "config/runtime.json"],
                    "workspace_skill_namespace": "workspace:",
                    "workspace_config": "research_preferences_with_host_precedence",
                    "skill_grants_permissions": False,
                    "plugin_enablement": "explicit_package_bound",
                    "mcp_default_status": "declaration_only",
                    "mcp_execution": "explicit_host_adapter_allowlist",
                    "mcp_research_support_max_calls": 2,
                    "mcp_research_support_counts_toward_tool_budget": True,
                    "mcp_transport_owner": "host",
                    "mcp_sdk_transports": ["stdio", "streamable_http"],
                    "mcp_sdk_lifecycle": "same_event_loop_owner_task",
                    "mcp_mounting": "explicit_host_lifespan",
                },
                "memory": {
                    "layers": ["transcript", "branch_working_memory", "dream_memory"],
                    "full_history_in_context": False,
                    "identity_namespace_locked": True,
                    "workspace_restore": "bounded_with_host_memory_precedence",
                    "dream_activation": "incremental_after_two_recorded_research_turns",
                    "dream_scope": "session_and_branch",
                    "dream_commits_model_batch_only": True,
                    "equipment_workspaces": "isolated_with_legacy_reuse",
                },
            },
            "skills": [
                skill.public_payload()
                for skill in sorted(
                    self.skills.values(),
                    key=lambda item: (
                        not item.public_payload()["recommended"],
                        item.source != "plugin",
                        item.skill_id,
                    ),
                )
            ],
            "plugins": [item.public_payload() for item in self.plugins],
            "mcp_servers": [
                server.public_payload()
                for plugin in self.plugins
                if plugin.plugin_id in enabled_plugins
                for server in plugin.mcp_servers
            ],
            "limits": {"max_active_skills": _MAX_ACTIVE_SKILLS},
        }


def load_capability_registry() -> DeepCapabilityRegistry:
    """Load a fresh snapshot so plugin changes apply on the next turn."""

    return DeepCapabilityRegistry.load_default()


def validate_workspace_capability_resource(
    kind: str,
    name: str,
    content: str,
) -> dict[str, Any]:
    """Validate an equipment-local capability file before durable commit.

    Only files that define runtime contracts receive strict schema checks.
    Supporting scripts, references and assets remain ordinary workspace state
    and never gain permissions merely by being present.
    """

    canonical_kind = str(kind or "").strip().lower()
    if canonical_kind not in {"skill", "plugin", "config"}:
        raise ValueError("unsupported workspace resource kind")
    raw_name = str(name or "").strip().replace("\\", "/")
    path = PurePosixPath(raw_name)
    if not raw_name or path.is_absolute() or ".." in path.parts or any(":" in part for part in path.parts):
        raise ValueError("workspace resource path is invalid")
    try:
        payload = str(content).encode("utf-8")
    except UnicodeError as exc:
        raise ValueError("workspace resource must be UTF-8 text") from exc
    result: dict[str, Any] = {
        "valid": True,
        "kind": canonical_kind,
        "name": path.as_posix(),
        "resource_type": "supporting_resource",
        "warnings": [],
        "contract": {},
    }

    def json_object(label: str) -> Mapping[str, Any]:
        try:
            decoded = json.loads(payload.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
            raise ValueError(f"{label} must be valid JSON") from exc
        if not isinstance(decoded, Mapping):
            raise ValueError(f"{label} must be a JSON object")
        return decoded

    def skill_contract(expected_name: str, skill_root: str) -> dict[str, Any]:
        row = DeepCapabilityRegistry._markdown_skill(payload, skill_root)
        if row is None:
            raise ValueError("SKILL.md requires valid YAML frontmatter")
        local_name = _text(row.get("skill_id") or row.get("name"), 64).lower()
        if not local_name or _SKILL_NAME.fullmatch(local_name) is None:
            raise ValueError("SKILL.md name must be a lowercase capability id")
        if local_name != expected_name:
            raise ValueError("SKILL.md name must match its containing directory")
        description = _text(row.get("description"), 600)
        if not description:
            raise ValueError("SKILL.md description is required")
        fields = {
            "steps": _string_list(row.get("steps"), limit=16, item_limit=500),
            "required_artifacts": _string_list(row.get("required_artifacts"), limit=16, item_limit=120),
            "quality_gates": _string_list(row.get("quality_gates"), limit=16, item_limit=500),
            "stop_conditions": _string_list(row.get("stop_conditions"), limit=12, item_limit=500),
        }
        missing = [field for field, values in fields.items() if not values]
        if missing:
            raise ValueError(
                "SKILL.md procedural contract is missing: " + ", ".join(missing)
            )
        declared_tools = _string_list(row.get("allowed_tools"), limit=32, item_limit=120)
        unknown_tools = [tool for tool in declared_tools if tool not in ALLOWED_TOOLS]
        warnings = []
        if unknown_tools:
            warnings.append(
                "unknown tool declarations do not grant execution permission: "
                + ", ".join(unknown_tools)
            )
        return {
            **result,
            "resource_type": "procedural_skill",
            "warnings": warnings,
            "contract": {
                "skill_name": local_name,
                "description": description,
                "steps": len(fields["steps"]),
                "required_artifacts": len(fields["required_artifacts"]),
                "quality_gates": len(fields["quality_gates"]),
                "stop_conditions": len(fields["stop_conditions"]),
                "allowed_tools": list(declared_tools),
            },
        }

    if canonical_kind == "skill" and path.name == "SKILL.md":
        if len(path.parts) != 2:
            raise ValueError("workspace Skill path must be <skill-id>/SKILL.md")
        return skill_contract(path.parts[0], path.parts[0])

    if canonical_kind == "plugin" and path.name == "SKILL.md":
        if len(path.parts) != 4 or path.parts[1] != "skills":
            raise ValueError("Plugin Skill path must be <plugin-id>/skills/<skill-id>/SKILL.md")
        return skill_contract(path.parts[2], "/".join(path.parts[1:3]))

    if canonical_kind == "plugin" and path.name == "plugin.json":
        if len(path.parts) != 2:
            raise ValueError("Plugin manifest path must be <plugin-id>/plugin.json")
        manifest = json_object("plugin.json")
        if manifest.get("$schema") != AGENT_PLUGIN_SCHEMA:
            raise ValueError("plugin.json must declare the Agent Plugin 1.0 schema")
        plugin_id = _text(manifest.get("name"), 64)
        if not plugin_id or _PLUGIN_NAME.fullmatch(plugin_id) is None:
            raise ValueError("plugin.json name is invalid")
        if plugin_id != path.parts[0]:
            raise ValueError("plugin.json name must match its containing directory")
        extensions = manifest.get("extensions", {})
        if not isinstance(extensions, Mapping):
            raise ValueError("plugin.json extensions must be an object")
        return {
            **result,
            "resource_type": "plugin_manifest",
            "contract": {"plugin_id": plugin_id, "schema": AGENT_PLUGIN_SCHEMA},
        }

    if canonical_kind == "plugin" and path.name == "mcp.json":
        if len(path.parts) != 2:
            raise ValueError("Plugin MCP path must be <plugin-id>/mcp.json")
        manifest = json_object("mcp.json")
        if manifest.get("$schema") != AGENT_PLUGIN_MCP_SCHEMA:
            raise ValueError("mcp.json must declare the Agent Plugin MCP 1.0 schema")
        if not isinstance(manifest.get("mcpServers"), Mapping):
            raise ValueError("mcp.json mcpServers must be an object")
        return {
            **result,
            "resource_type": "mcp_declaration",
            "contract": {
                "servers": len(manifest["mcpServers"]),
                "execution_status": "declaration_only",
            },
        }

    if canonical_kind == "config" and path.as_posix() == "runtime.json":
        config = json_object("runtime.json")
        allowed = {"active_skill_ids", "disabled_skill_ids", "deep_runtime_budget"}
        unknown = sorted(str(key) for key in config if key not in allowed)
        if unknown:
            raise ValueError("runtime.json contains unsupported keys: " + ", ".join(unknown))
        for key in ("active_skill_ids", "disabled_skill_ids"):
            value = config.get(key, [])
            if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
                raise ValueError(f"runtime.json {key} must be a string array")
        budget = config.get("deep_runtime_budget", {})
        if not isinstance(budget, Mapping):
            raise ValueError("runtime.json deep_runtime_budget must be an object")
        for key, value in budget.items():
            if key not in {"max_turns", "max_tool_calls"}:
                raise ValueError(f"runtime.json budget key is unsupported: {key}")
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 12:
                raise ValueError(f"runtime.json {key} must be an integer from 0 to 12")
        active = set(config.get("active_skill_ids", []))
        disabled = set(config.get("disabled_skill_ids", []))
        warnings = []
        overlap = sorted(active & disabled)
        if overlap:
            warnings.append("skills listed as active and disabled resolve to disabled: " + ", ".join(overlap))
        return {
            **result,
            "resource_type": "runtime_config",
            "warnings": warnings,
            "contract": {
                "active_skills": len(active),
                "disabled_skills": len(disabled),
                "budget": dict(budget),
            },
        }

    if path.suffix.lower() == ".json":
        json_object(path.name)
    result["warnings"] = ["supporting resource is stored but is not loaded as a capability contract"]
    return result


__all__ = [
    "AGENT_PLUGIN_MCP_SCHEMA",
    "AGENT_PLUGIN_SCHEMA",
    "DeepCapabilityRegistry",
    "DeepPlugin",
    "MCPDeclaration",
    "ProceduralSkill",
    "load_capability_registry",
    "validate_workspace_capability_resource",
]
