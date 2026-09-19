from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil

import pytest

from equipment_deep_research.deep_runtime import capabilities as capability_module
from equipment_deep_research.deep_runtime.capabilities import (
    AGENT_PLUGIN_MCP_SCHEMA,
    AGENT_PLUGIN_SCHEMA,
    DeepCapabilityRegistry,
    validate_workspace_capability_resource,
)
from equipment_deep_research.deep_runtime.planner import ALLOWED_TOOLS
from equipment_deep_research.deep_runtime.provider_runtime import ProviderRuntime
from equipment_deep_research.deep_runtime.workspace import DeepWorkspace


def _harness(path: Path) -> Path:
    path.write_text(
        """
profiles: []
knowledge_packs: []
skills:
  - skill_id: counterfactual_triz_innovation
    triggers: [反事实]
    allowed_tools: [generate_counterfactual_option]
    steps: [改变关键前提, 比较常规路径]
    required_artifacts: [WinningReasoningNode]
    quality_gates: [方向可证伪]
    stop_conditions: [形成互异方向]
""".strip(),
        encoding="utf-8",
    )
    return path


def _plugin(root: Path, *, default_enabled: bool = False) -> Path:
    plugin = root / "test-methods"
    plugin.mkdir(parents=True)
    (plugin / "plugin.json").write_text(
        json.dumps(
            {
                "$schema": AGENT_PLUGIN_SCHEMA,
                "name": "test-methods",
                "description": "test procedures",
                "extensions": {
                    "dev.equipment-deep-research": {
                        "displayName": "测试方法包",
                        "defaultEnabled": default_enabled,
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (plugin / "skills.yaml").write_text(
        """
skills:
  - skill_id: red-team
    description: 检验对手最低成本反制
    triggers: [反制]
    applies_to: [deepen]
    allowed_tools: [test_competing_hypothesis]
    steps: [提出最低成本反制, 构造降级模式]
    required_artifacts: [CountermeasureStressTest]
    quality_gates: [反制与机理对应]
    stop_conditions: [已找到决定性反制]
""".strip(),
        encoding="utf-8",
    )
    (plugin / "mcp.json").write_text(
        json.dumps(
            {
                "$schema": AGENT_PLUGIN_MCP_SCHEMA,
                "mcpServers": {
                    "evidence": {"type": "stdio", "command": "evidence-mcp"}
                },
            }
        ),
        encoding="utf-8",
    )
    return plugin


def _registry(tmp_path: Path, *, default_enabled: bool = False) -> DeepCapabilityRegistry:
    plugins = tmp_path / "plugins"
    _plugin(plugins, default_enabled=default_enabled)
    return DeepCapabilityRegistry(
        harness_path=_harness(tmp_path / "harness.yaml"),
        plugins_root=plugins,
        state_path=tmp_path / "runtime" / "plugins.json",
    )


def _workspace_skill(workspace: DeepWorkspace, name: str = "frontier") -> None:
    workspace.write_resource("skill", f"{name}/SKILL.md", f"""---
name: {name}
description: Explore an uncertain frontier
triggers: [frontier]
procedure:
  applies_to: [deepen]
  steps: [Identify assumptions, Compare alternatives]
  required_artifacts: [AlternativeMap]
  quality_gates: [Distinct mechanisms]
  stop_conditions: [No new assumptions]
---
Keep competing assumptions visible.
""")


def test_workspace_capability_resource_validation_enforces_procedural_contracts() -> None:
    skill = """---
name: frontier
description: Explore an uncertain frontier
procedure:
  steps: [Identify assumptions, Compare alternatives]
  required_artifacts: [AlternativeMap]
  quality_gates: [Distinct mechanisms]
  stop_conditions: [No new assumptions]
---
Keep competing assumptions visible.
"""
    validated = validate_workspace_capability_resource(
        "skill", "frontier/SKILL.md", skill
    )
    assert validated["valid"] is True
    assert validated["resource_type"] == "procedural_skill"
    assert validated["contract"]["steps"] == 2

    with pytest.raises(ValueError, match="procedural contract is missing"):
        validate_workspace_capability_resource(
            "skill",
            "prompt/SKILL.md",
            "---\nname: prompt\ndescription: free form\n---\nJust a prompt",
        )
    with pytest.raises(ValueError, match="match its containing directory"):
        validate_workspace_capability_resource(
            "skill", "other/SKILL.md", skill
        )


def test_workspace_capability_resource_validation_fences_plugins_and_runtime_config() -> None:
    plugin = validate_workspace_capability_resource(
        "plugin",
        "local-methods/plugin.json",
        json.dumps({
            "$schema": AGENT_PLUGIN_SCHEMA,
            "name": "local-methods",
            "extensions": {"dev.equipment-deep-research": {"defaultEnabled": False}},
        }),
    )
    assert plugin["resource_type"] == "plugin_manifest"
    assert plugin["contract"]["plugin_id"] == "local-methods"

    config = validate_workspace_capability_resource(
        "config",
        "runtime.json",
        json.dumps({
            "active_skill_ids": ["workspace:frontier"],
            "disabled_skill_ids": [],
            "deep_runtime_budget": {"max_turns": 8, "max_tool_calls": 8},
        }),
    )
    assert config["resource_type"] == "runtime_config"
    assert config["contract"]["budget"]["max_turns"] == 8

    with pytest.raises(ValueError, match="unsupported keys"):
        validate_workspace_capability_resource(
            "config",
            "runtime.json",
            json.dumps({"provider": "forged", "s6_confirmed": True}),
        )


def test_workspace_capabilities_are_scoped_and_progressive(tmp_path):
    registry = _registry(tmp_path)
    workspace = DeepWorkspace.open(tmp_path / "equipment-a")
    _workspace_skill(workspace)
    workspace.write_resource("skill", "frontier/references/method.md", "method details")
    local = registry.with_workspace(workspace)
    selected = local.select_skills(text="frontier", plan=["deepen"])
    assert selected[0].skill_id == "workspace:frontier"
    assert selected[0].source == "workspace"
    assert selected[0].resources == ("references/method.md",)
    assert "Keep competing assumptions" in local.prompt_context(selected)
    assert "workspace:frontier" not in registry.skills
    assert "workspace:frontier" not in registry.with_workspace(DeepWorkspace.open(tmp_path / "equipment-b")).skills
    assert "workspace:frontier" not in [item.skill_id for item in local.select_skills(text="frontier", plan=["challenge"])]
    assert str(tmp_path) not in json.dumps(local.public_payload())


def test_workspace_plugins_require_exact_package_enablement(tmp_path):
    registry = _registry(tmp_path)
    workspace = DeepWorkspace.open(tmp_path / "workspace")
    _plugin(workspace.plugins_dir)
    # A deployment package with the same identity keeps precedence.
    assert len(registry.with_workspace(workspace).plugins) == 1
    local_registry = DeepCapabilityRegistry(
        harness_path=registry.harness_path, plugins_root=workspace.plugins_dir,
        state_path=workspace.config_dir / "plugins.json",
    )
    local_registry.set_plugin_enabled("test-methods", True)
    empty = DeepCapabilityRegistry(
        harness_path=registry.harness_path, plugins_root=tmp_path / "empty-plugins",
        state_path=tmp_path / "empty-state.json",
    )
    assert "test-methods:red-team" in empty.with_workspace(workspace).skills
    workspace.write_resource("plugin", "test-methods/skills.yaml", "skills: []")
    assert "test-methods:red-team" not in empty.with_workspace(workspace).skills


def test_workspace_config_projects_only_research_preferences(tmp_path):
    registry = _registry(tmp_path)
    workspace = DeepWorkspace.open(tmp_path / "workspace")
    _workspace_skill(workspace)
    workspace.write_resource("config", "runtime.json", json.dumps({
        "active_skill_ids": ["workspace:frontier"],
        "disabled_skill_ids": ["counterfactual_triz_innovation"],
        "deep_runtime_budget": {"max_turns": 999, "max_tool_calls": True},
        "equipment_identity": {"name": "forged"}, "s6_confirmed": True,
        "provider": "forged", "mcp_servers": ["forged"],
    }))
    local = registry.with_workspace(workspace)
    assert local.workspace_config == {
        "active_skill_ids": ["workspace:frontier"],
        "disabled_skill_ids": ["counterfactual_triz_innovation"],
        "deep_runtime_budget": {"max_turns": 12},
    }
    assert "counterfactual_triz_innovation" not in local.skills
    assert "counterfactual_triz_innovation" in registry.skills


def test_workspace_skills_and_config_reject_symlinks_and_invalid_contracts(tmp_path):
    registry = _registry(tmp_path)
    workspace = DeepWorkspace.open(tmp_path / "workspace")
    _workspace_skill(workspace)
    workspace.write_resource("skill", "invalid/SKILL.md", "---\nname: invalid\ndescription: prompt\n---\nFreeform prompt")
    assert "workspace:invalid" not in registry.with_workspace(workspace).skills
    outside = tmp_path / "outside.json"
    outside.write_text('{"active_skill_ids": ["workspace:frontier"]}')
    (workspace.config_dir / "runtime.json").symlink_to(outside)
    assert registry.with_workspace(workspace).workspace_config == {}
    (workspace.skills_dir / "frontier" / "references").symlink_to(tmp_path)
    assert "workspace:frontier" not in registry.with_workspace(workspace).skills


def test_procedural_skills_are_progressively_selected(tmp_path: Path) -> None:
    registry = _registry(tmp_path, default_enabled=True)
    registry.set_plugin_enabled("test-methods", True)
    registry = DeepCapabilityRegistry(
        harness_path=registry.harness_path,
        plugins_root=registry.plugins_root,
        state_path=registry.state_path,
    )

    selected = registry.select_skills(
        text="请做反制压力测试",
        plan=["deepen"],
    )

    ids = [item.skill_id for item in selected]
    assert ids[0] == "test-methods:red-team"
    assert "counterfactual_triz_innovation" in ids
    prompt = registry.prompt_context(selected)
    assert "Steps:" in prompt
    assert "Required artifacts:" in prompt
    assert "Quality gates:" in prompt
    assert "Stop conditions:" in prompt


def test_plugin_activation_is_bound_to_package_fingerprint(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    assert registry.plugins[0].enabled is False

    enabled = registry.set_plugin_enabled("test-methods", True)
    assert enabled.enabled is True
    assert "test-methods:red-team" in DeepCapabilityRegistry(
        harness_path=registry.harness_path,
        plugins_root=registry.plugins_root,
        state_path=registry.state_path,
    ).skills

    # A changed package must be reviewed and explicitly re-enabled.
    skill_file = registry.plugins_root / "test-methods" / "skills.yaml"
    skill_file.write_text(skill_file.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    changed = DeepCapabilityRegistry(
        harness_path=registry.harness_path,
        plugins_root=registry.plugins_root,
        state_path=registry.state_path,
    )
    assert changed.plugins[0].enabled is False
    assert "test-methods:red-team" not in changed.skills


def test_package_changed_after_discovery_fails_closed_when_enabled(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path)
    skill_file = registry.plugins_root / "test-methods" / "skills.yaml"
    skill_file.write_text(
        skill_file.read_text(encoding="utf-8") + "\n# changed before enable\n",
        encoding="utf-8",
    )

    result = registry.set_plugin_enabled("test-methods", True)

    assert result.enabled is False
    refreshed = DeepCapabilityRegistry(
        harness_path=registry.harness_path,
        plugins_root=registry.plugins_root,
        state_path=registry.state_path,
    )
    assert refreshed.plugins[0].enabled is False
    assert "test-methods:red-team" not in refreshed.skills


def test_public_catalog_hides_plugin_paths_and_mcp_commands(tmp_path: Path) -> None:
    registry = _registry(tmp_path, default_enabled=True)
    registry.set_plugin_enabled("test-methods", True)
    registry = DeepCapabilityRegistry(
        harness_path=registry.harness_path,
        plugins_root=registry.plugins_root,
        state_path=registry.state_path,
    )

    payload = registry.public_payload()

    assert payload["plugins"][0]["plugin_id"] == "test-methods"
    assert payload["mcp_servers"] == [
        {
            "server_id": "test-methods:evidence",
            "transport": "stdio",
            "plugin_id": "test-methods",
            "execution_status": "declaration_only",
        }
    ]
    rendered = json.dumps(payload, ensure_ascii=False)
    assert str(tmp_path) not in rendered
    assert "evidence-mcp" not in rendered


def test_public_catalog_exposes_runtime_ownership_and_execution_contract(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path)
    contract = registry.public_payload()["runtime_contract"]

    assert set(contract["agent_loop"]["actions"]) == set(ALLOWED_TOOLS)
    for method in contract["provider"]["methods"]:
        assert callable(getattr(ProviderRuntime, method))

    contract["agent_loop"]["actions"].clear()
    assert registry.public_payload()["runtime_contract"]["agent_loop"]["actions"]


def test_manifest_default_enabled_does_not_bypass_explicit_consent(tmp_path: Path) -> None:
    registry = _registry(tmp_path, default_enabled=True)

    assert registry.plugins[0].default_enabled is True
    assert registry.plugins[0].enabled is False
    assert "test-methods:red-team" not in registry.skills


def test_plugin_activation_is_bound_to_install_root(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    registry.set_plugin_enabled("test-methods", True)

    moved_root = tmp_path / "moved"
    moved_plugins = moved_root / "plugins"
    moved_plugins.mkdir(parents=True)
    source = registry.plugins_root / "test-methods"
    target = moved_plugins / "test-methods"
    target.mkdir()
    for source_file in source.iterdir():
        (target / source_file.name).write_bytes(source_file.read_bytes())

    moved = DeepCapabilityRegistry(
        harness_path=registry.harness_path,
        plugins_root=moved_plugins,
        state_path=registry.state_path,
    )
    assert moved.plugins[0].enabled is False


def test_concurrent_plugin_toggles_preserve_sibling_state(tmp_path: Path) -> None:
    first = _registry(tmp_path)
    source = first.plugins_root / "test-methods"
    sibling = first.plugins_root / "second-methods"
    shutil.copytree(source, sibling)
    manifest_path = sibling / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["name"] = "second-methods"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    registry_a = DeepCapabilityRegistry(
        harness_path=first.harness_path,
        plugins_root=first.plugins_root,
        state_path=first.state_path,
    )
    registry_b = DeepCapabilityRegistry(
        harness_path=first.harness_path,
        plugins_root=first.plugins_root,
        state_path=first.state_path,
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(registry_a.set_plugin_enabled, "test-methods", True),
            pool.submit(registry_b.set_plugin_enabled, "second-methods", True),
        ]
        for future in futures:
            future.result()

    refreshed = DeepCapabilityRegistry(
        harness_path=first.harness_path,
        plugins_root=first.plugins_root,
        state_path=first.state_path,
    )
    assert {item.plugin_id for item in refreshed.plugins if item.enabled} == {
        "test-methods",
        "second-methods",
    }


def test_free_form_plugin_prompt_without_procedure_is_ignored(tmp_path: Path) -> None:
    registry = _registry(tmp_path, default_enabled=True)
    plugin = registry.plugins_root / "test-methods"
    (plugin / "skills.yaml").write_text(
        "skills:\n  - skill_id: prompt-only\n    description: 只有一句提示\n",
        encoding="utf-8",
    )

    refreshed = DeepCapabilityRegistry(
        harness_path=registry.harness_path,
        plugins_root=registry.plugins_root,
        state_path=tmp_path / "another-state.json",
    )

    assert all(item.skill_id != "test-methods:prompt-only" for item in refreshed.plugins[0].skills)


def test_markdown_skill_loads_instructions_and_indexes_bounded_resources(
    tmp_path: Path,
) -> None:
    plugins = tmp_path / "plugins"
    plugin = _plugin(plugins)
    (plugin / "skills.yaml").unlink()
    skill_root = plugin / "skills" / "structured-method"
    references = skill_root / "references"
    references.mkdir(parents=True)
    (references / "checklist.md").write_text("# 审查表\n逐项核对假设。", encoding="utf-8")
    (skill_root / "SKILL.md").write_text(
        """---
name: structured-method
description: 带正文的程序方法
procedure:
  triggers: [审查]
  applies_to: [deepen]
  allowed_tools: [test_competing_hypothesis]
  steps: [识别假设, 逐项审查]
  required_artifacts: [ReviewRecord]
  quality_gates: [每个结论都有依据]
  stop_conditions: [审查记录闭合]
---
# 执行说明

先识别隐含假设，再按审查表逐项核对。
""".strip(),
        encoding="utf-8",
    )
    registry = DeepCapabilityRegistry(
        harness_path=_harness(tmp_path / "harness.yaml"),
        plugins_root=plugins,
        state_path=tmp_path / "runtime" / "plugins.json",
    )
    registry.set_plugin_enabled("test-methods", True)
    registry = DeepCapabilityRegistry(
        harness_path=registry.harness_path,
        plugins_root=registry.plugins_root,
        state_path=registry.state_path,
    )

    skill = registry.skills["test-methods:structured-method"]
    assert "先识别隐含假设" in skill.instructions
    assert skill.resources == ("references/checklist.md",)
    assert skill.public_payload()["has_instructions"] is True
    assert "执行说明" in registry.prompt_context([skill])


def test_unmet_skill_requirements_keep_procedure_out_of_runtime(tmp_path: Path) -> None:
    plugins = tmp_path / "plugins"
    plugin = _plugin(plugins)
    (plugin / "skills.yaml").write_text(
        """skills:
  - skill_id: gated-method
    description: 依赖外部工具的方法
    triggers: [依赖]
    applies_to: [deepen]
    allowed_tools: [test_competing_hypothesis]
    steps: [执行依赖检查]
    required_artifacts: [Check]
    quality_gates: [检查通过]
    stop_conditions: [检查完成]
    requires:
      bins: [definitely-missing-deep-research-cli]
      env: [DEFINITELY_MISSING_DEEP_RESEARCH_TOKEN]
""".strip(),
        encoding="utf-8",
    )
    registry = DeepCapabilityRegistry(
        harness_path=_harness(tmp_path / "harness.yaml"),
        plugins_root=plugins,
        state_path=tmp_path / "runtime" / "plugins.json",
    )
    enabled = registry.set_plugin_enabled("test-methods", True)
    gated = next(item for item in enabled.skills if item.skill_id.endswith(":gated-method"))
    assert gated.available is False
    assert gated.missing_requirements == (
        "CLI:definitely-missing-deep-research-cli",
        "ENV:DEFINITELY_MISSING_DEEP_RESEARCH_TOKEN",
    )

    refreshed = DeepCapabilityRegistry(
        harness_path=registry.harness_path,
        plugins_root=registry.plugins_root,
        state_path=registry.state_path,
    )
    assert "test-methods:gated-method" not in refreshed.skills


def test_plugin_symlink_escape_is_rejected(tmp_path: Path) -> None:
    plugins = tmp_path / "plugins"
    plugin = _plugin(plugins)
    outside = tmp_path / "outside.md"
    outside.write_text("outside package", encoding="utf-8")
    references = plugin / "references"
    references.mkdir()
    try:
        (references / "escape.md").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")

    registry = DeepCapabilityRegistry(
        harness_path=_harness(tmp_path / "harness.yaml"),
        plugins_root=plugins,
        state_path=tmp_path / "runtime" / "plugins.json",
    )

    assert registry.plugins == ()


def test_plugin_root_symlink_alias_is_rejected(tmp_path: Path) -> None:
    plugins = tmp_path / "plugins"
    real_plugin = _plugin(plugins)
    try:
        (plugins / "aliased-methods").symlink_to(real_plugin, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")

    registry = DeepCapabilityRegistry(
        harness_path=_harness(tmp_path / "harness.yaml"),
        plugins_root=plugins,
        state_path=tmp_path / "runtime" / "plugins.json",
    )

    assert [item.root.name for item in registry.plugins] == ["test-methods"]


def test_skill_root_path_traversal_is_rejected(tmp_path: Path) -> None:
    plugins = tmp_path / "plugins"
    plugin = _plugin(plugins)
    (plugin / "skills.yaml").write_text(
        """skills:
  - skill_id: escaped
    _skill_root: ../../outside
    steps: [读取外部资源]
    required_artifacts: [Check]
    quality_gates: [检查通过]
    stop_conditions: [检查完成]
""".strip(),
        encoding="utf-8",
    )

    registry = DeepCapabilityRegistry(
        harness_path=_harness(tmp_path / "harness.yaml"),
        plugins_root=plugins,
        state_path=tmp_path / "runtime" / "plugins.json",
    )

    assert registry.plugins
    assert registry.plugins[0].skills == ()


def test_package_changed_between_snapshot_and_verification_is_disabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    registry = _registry(tmp_path)
    enabled = registry.set_plugin_enabled("test-methods", True)
    assert enabled.enabled is True
    skill_file = registry.plugins_root / "test-methods" / "skills.yaml"
    changed = skill_file.read_text(encoding="utf-8").replace(
        "提出最低成本反制", "篡改后的未授权步骤"
    )
    original = DeepCapabilityRegistry._package_snapshot.__func__
    calls = 0

    def racing_snapshot(cls, root: Path):
        nonlocal calls
        snapshot = original(cls, root)
        calls += 1
        if calls == 1:
            skill_file.write_text(changed, encoding="utf-8")
        return snapshot

    monkeypatch.setattr(
        DeepCapabilityRegistry,
        "_package_snapshot",
        classmethod(racing_snapshot),
    )

    refreshed = DeepCapabilityRegistry(
        harness_path=registry.harness_path,
        plugins_root=registry.plugins_root,
        state_path=registry.state_path,
    )

    assert calls >= 2
    assert refreshed.plugins[0].enabled is False
    assert refreshed.plugins[0].skills[0].steps[0] == "提出最低成本反制"
    assert "test-methods:red-team" not in refreshed.skills


def test_disabled_package_file_count_is_bounded(
    tmp_path: Path,
    monkeypatch,
) -> None:
    plugins = tmp_path / "plugins"
    plugin = _plugin(plugins)
    (plugin / "extra.txt").write_text("extra", encoding="utf-8")
    monkeypatch.setattr(capability_module, "_MAX_PLUGIN_FILES", 3)

    registry = DeepCapabilityRegistry(
        harness_path=_harness(tmp_path / "harness.yaml"),
        plugins_root=plugins,
        state_path=tmp_path / "runtime" / "plugins.json",
    )

    assert registry.plugins == ()


def test_disabled_package_single_file_size_is_bounded(
    tmp_path: Path,
    monkeypatch,
) -> None:
    plugins = tmp_path / "plugins"
    plugin = _plugin(plugins)
    largest_existing = max(path.stat().st_size for path in plugin.iterdir())
    monkeypatch.setattr(
        capability_module,
        "_MAX_PLUGIN_FILE_BYTES",
        largest_existing,
    )
    (plugin / "oversized.bin").write_bytes(b"x" * (largest_existing + 1))

    registry = DeepCapabilityRegistry(
        harness_path=_harness(tmp_path / "harness.yaml"),
        plugins_root=plugins,
        state_path=tmp_path / "runtime" / "plugins.json",
    )

    assert registry.plugins == ()


def test_disabled_package_total_size_is_bounded(
    tmp_path: Path,
    monkeypatch,
) -> None:
    plugins = tmp_path / "plugins"
    plugin = _plugin(plugins)
    existing_size = sum(path.stat().st_size for path in plugin.iterdir())
    monkeypatch.setattr(
        capability_module,
        "_MAX_PLUGIN_TOTAL_BYTES",
        existing_size,
    )
    (plugin / "extra.txt").write_text("extra", encoding="utf-8")

    registry = DeepCapabilityRegistry(
        harness_path=_harness(tmp_path / "harness.yaml"),
        plugins_root=plugins,
        state_path=tmp_path / "runtime" / "plugins.json",
    )

    assert registry.plugins == ()


def test_declared_applies_to_filters_requested_and_triggered_skills(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path)
    registry.set_plugin_enabled("test-methods", True)
    registry = DeepCapabilityRegistry(
        harness_path=registry.harness_path,
        plugins_root=registry.plugins_root,
        state_path=registry.state_path,
    )

    incompatible_requested = registry.select_skills(
        text="$test-methods:red-team 反制",
        plan=["author_s6"],
        requested=["test-methods:red-team"],
    )
    compatible_requested = registry.select_skills(
        text="$test-methods:red-team",
        plan=["deepen"],
        requested=["test-methods:red-team"],
    )

    assert "test-methods:red-team" not in {
        item.skill_id for item in incompatible_requested
    }
    assert "test-methods:red-team" in {
        item.skill_id for item in compatible_requested
    }
