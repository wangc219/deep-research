"""内置定义发现与失败边界。"""

from importlib import invalidate_caches
import sys
from typing import get_type_hints

import pytest
from langgraph.prebuilt.tool_node import ToolRuntime

from platform_core.agents import buildin, presets
from platform_core.agents.buildin.chatbot.graph import ChatbotAgent
from platform_core.agents.buildin.subagent.graph import SubAgentBackend
from platform_core.agents.middlewares.subagent_task import SUBAGENT_SYSTEM_PROMPT
from platform_core.agents.skills import service as skill_service
from platform_core.agents.toolkits.buildin.tools import PUBLIC_SEARCH_DESCRIPTION
from platform_core.agents.toolkits.equipment import (
    equipment_deep_context,
    save_equipment_capability_draft,
    start_equipment_research,
)


@pytest.fixture(autouse=True)
def clean_discovery_test_modules():
    """临时模块不能影响其他发现测试。"""
    before = set(sys.modules)
    yield
    for name in set(sys.modules) - before:
        if name.startswith(("platform_core.agents.presets.test_", "platform_core.agents.buildin.test_")):
            del sys.modules[name]


def test_preset_discovery_includes_shipping_roles():
    """发布内容完整，深度研究保持原有委派关系。"""
    found = {preset.slug: preset for preset in presets.discover_agent_presets()}
    assert set(found) == {
        "default-chatbot",
        "general-purpose",
        "web-search",
        "deep-research",
        "equipment-capability-portrait",
        "weapon-equipment-scheme",
        "research-explorer",
        "fact-verifier",
    }
    assert found["deep-research"].context["subagents"] == ["research-explorer", "fact-verifier"]
    scheme = found["weapon-equipment-scheme"]
    assert scheme.context["subagents"] == ["research-explorer", "fact-verifier"]
    assert scheme.sync_existing is True
    assert "能力目标" in scheme.context["system_prompt"]
    assert "具体实现" in scheme.context["system_prompt"]
    assert "equipment-deep-conversation" in scheme.context["skills"]
    portrait = found["equipment-capability-portrait"]
    assert portrait.context["subagents"] == ["research-explorer", "fact-verifier"]
    assert "概述" in portrait.context["system_prompt"]
    assert "制胜逻辑机理" in portrait.context["system_prompt"]
    assert "save_equipment_capability_draft" in portrait.context["system_prompt"]
    assert "equipment-deep-conversation" in portrait.context["skills"]
    assert found["general-purpose"].context == {}
    assert found["default-chatbot"].backend_id == "ChatbotAgent"
    assert found["default-chatbot"].context["subagents"] == ["research-explorer", "fact-verifier"]
    assert found["fact-verifier"].backend_id == "SubAgentBackend"
    explorer = found["research-explorer"]
    assert "主智能体" in explorer.context["system_prompt"]
    assert "required_terms" in explorer.context["system_prompt"]
    assert "academic_search" in explorer.context["system_prompt"]
    assert "信息增益循环" in explorer.context["system_prompt"]
    assert "紧凑证据包" in explorer.context["system_prompt"]
    assert "单个证据问题" in explorer.description


@pytest.mark.parametrize("slug", ["weapon-equipment-scheme"])
def test_smart_chat_equipment_schemes_use_the_seven_chapter_r_and_d_template(slug):
    """专用方案角色保留原有七章研发报告能力。"""
    found = {preset.slug: preset for preset in presets.discover_agent_presets()}
    prompt = found[slug].context["system_prompt"]

    assert "武器装备研发技术方案报告" in prompt
    assert "面向研发人员 · 技术路线设计 · 关键问题攻关 · 工程实现" in prompt
    assert "章节—核心内容—主要回答的问题" in prompt
    for chapter in (
        "项目概述与研发需求",
        "总体技术方案",
        "核心技术体系",
        "关键技术攻关",
        "技术实现方案",
        "技术路线与研发计划",
        "预期成果与应用价值",
    ):
        assert chapter in prompt


@pytest.mark.parametrize("slug", ["default-chatbot", "deep-research", "weapon-equipment-scheme"])
def test_technical_solutions_form_weapons_through_the_s3_s4_winning_gate(slug):
    """技术方案内生成或重构装备时，先收敛为具体作战制胜新质武器。"""
    found = {preset.slug: preset for preset in presets.discover_agent_presets()}
    prompt = found[slug].context["system_prompt"]

    for requirement in (
        "物理武器实体",
        "接敌关系",
        "作用载体与机理",
        "可观察直接战果",
        "分系统或支撑条件",
    ):
        assert requirement in prompt


@pytest.mark.parametrize("slug", ["default-chatbot", "deep-research"])
def test_conversation_presets_default_to_research_explorer_for_external_evidence(slug):
    """两个入口预加载研究能力，并由模型动态决定直接检索或委派。"""
    found = {preset.slug: preset for preset in presets.discover_agent_presets()}
    context = found[slug].context
    prompt = context["system_prompt"]

    assert "research-explorer" in context["subagents"]
    assert "deep-research" in context["preload_skills"]
    assert presets.DEFAULT_RESEARCH_POLICY in prompt
    assert "subagent_start" in prompt and "subagent_await" in prompt
    assert "简单问题可以直接检索或只委派一个探索员" in prompt
    assert "分片数量、先后关系和并行度" in prompt
    assert "动态决定" in prompt
    assert "单一事实检索也可委派 research-explorer" in SUBAGENT_SYSTEM_PROMPT


@pytest.mark.parametrize("slug", ["default-chatbot", "deep-research"])
def test_conversation_presets_use_chinese_for_visible_execution_feedback(slug):
    """智能与深研对话的计划、进度、工具和子智能体反馈默认使用中文。"""
    found = {preset.slug: preset for preset in presets.discover_agent_presets()}
    prompt = found[slug].context["system_prompt"]

    for requirement in ("默认使用简体中文反馈执行过程与最终结果", "用户明确指定其他语言时从其要求"):
        assert requirement in prompt


@pytest.mark.parametrize("slug", ["default-chatbot", "deep-research"])
def test_conversation_presets_require_combat_equipment_outputs(slug):
    """智能与深研对话形成装备时不得停在能力方向或软件体系。"""
    found = {preset.slug: preset for preset in presets.discover_agent_presets()}
    prompt = found[slug].context["system_prompt"]

    for requirement in (
        "可单独指认、研制、部署和试验",
        "具体物理武器实体",
        "装备名称与身份",
        "场景和作用对象",
        "部署与接敌方式",
        "总体构型与关键分系统",
        "作用载体与机理",
        "可观察直接战果",
        "敌方原有应对为何失配",
        "工程瓶颈",
        "可证伪验证路径",
    ):
        assert requirement in prompt
    assert "只能作为分系统或支撑条件" in prompt
    assert "默认一次并行委派3个" not in prompt
    assert "6至8次" not in prompt
    assert "1至3个" not in prompt


def test_weapon_assistant_turns_future_equipment_discussion_into_concrete_candidates():
    """用户只说方向或能力时，武器装备助手也必须落到可研制、可验证的装备实体。"""
    found = {preset.slug: preset for preset in presets.discover_agent_presets()}
    prompt = found["default-chatbot"].context["system_prompt"]

    for requirement in (
        "未来作战需求、能力缺口、装备创新、技术赋能",
        "现有装备事实",
        "装备名称与身份",
        "场景和作用对象",
        "部署与接敌方式",
        "总体构型与关键分系统",
        "可证伪验证路径",
        "智能化、无人化、集群化、多域协同",
    ):
        assert requirement in prompt


def test_deep_research_skill_defaults_future_equipment_topics_to_concrete_equipment():
    """预加载深研技能提供通用长程编排而不固化业务阶段。"""
    specs = {spec["slug"]: spec for spec in skill_service.list_builtin_skill_specs()}
    content = (specs["deep-research"]["source_dir"] / "SKILL.md").read_text(encoding="utf-8")

    assert "智能对话是唯一入口和总控" in content
    assert "动态规划" in content
    assert "正交问题" in content
    assert "进展.md" in content
    assert "模型已有知识" in content
    assert "创新假设" in content


@pytest.mark.parametrize("slug", ["default-chatbot", "deep-research"])
def test_conversation_presets_use_adaptive_evidence_led_generation(slug):
    """装备研究由证据塑形，但不固化 Agent 数量或检索配额。"""
    found = {preset.slug: preset for preset in presets.discover_agent_presets()}
    preset = found[slug]
    prompt = preset.context["system_prompt"]
    assert preset.context["subagents"] == ["research-explorer", "fact-verifier"]
    assert "而不是按网页、论文、地区等资料渠道机械分工" in prompt
    assert "分片数量、先后关系和并行度" in prompt
    assert "广度发现—缺口识别—定向深挖" in prompt
    assert "required_terms" in prompt
    assert "AMiner" in prompt
    assert "完整摘要" in prompt
    assert "主智能体" in prompt
    assert "让证据塑造构想" in prompt
    assert "默认一次并行委派3个" not in prompt
    assert "6至8次" not in prompt


@pytest.mark.parametrize("slug", ["default-chatbot", "deep-research", "research-explorer"])
def test_research_prompts_choose_sources_by_information_gain(slug):
    """检索按证据缺口自适应，不再强制固定地域和调用次数。"""
    found = {preset.slug: preset for preset in presets.discover_agent_presets()}
    prompt = found[slug].context["system_prompt"]

    assert "required_terms" in prompt
    assert "固定" in prompt
    assert "信息增益" in prompt or "改变结论" in prompt
    for rigid_rule in ("国内角度", "国外角度", "6至8次", "6 至 8 次", "81.cn"):
        assert rigid_rule not in prompt


def test_public_search_tool_teaches_adaptive_evidence_queries():
    """工具说明只约束相关性和证据质量，不规定业务检索流水线。"""
    for requirement in (
        "明确证据缺口",
        "required_terms",
        "required_term_groups",
        "一手或高权威来源",
        "信息饱和",
        "status=degraded",
    ):
        assert requirement in PUBLIC_SEARCH_DESCRIPTION
    assert "6-8 次" not in PUBLIC_SEARCH_DESCRIPTION
    assert "81.cn" not in PUBLIC_SEARCH_DESCRIPTION


def test_deep_research_skill_uses_adaptive_multi_source_research():
    """深研技能支持广度、深挖和来源降级，不绑定固定地域配额。"""
    specs = {spec["slug"]: spec for spec in skill_service.list_builtin_skill_specs()}
    content = (specs["deep-research"]["source_dir"] / "SKILL.md").read_text(encoding="utf-8")

    for requirement in (
        "广度发现—缺口识别—定向深挖",
        "AMiner",
        "Open Websearch",
        "模型知识",
        "信息饱和",
        "覆盖缺口",
    ):
        assert requirement in content
    assert "最多 8 次网页检索" not in content


def test_new_preset_file_is_discovered_without_registry(tmp_path, monkeypatch):
    """新增真实模块即可发现，不需要编辑启动入口。"""
    monkeypatch.setattr(presets, "__file__", str(tmp_path / "__init__.py"))
    monkeypatch.setattr(presets, "__path__", [str(tmp_path)])
    (tmp_path / "test_new_role.py").write_text(
        "from platform_core.agents.presets import AgentPreset\n"
        'PRESET = AgentPreset(slug="new-role", name="新增角色", description="测试发现")\n'
    )
    invalidate_caches()
    found = presets.discover_agent_presets()
    assert [(item.slug, item.name) for item in found] == [("new-role", "新增角色")]


@pytest.mark.parametrize(
    ("source", "error", "message"),
    [
        ("PRESET = None\n", TypeError, "必须是 AgentPreset"),
        ('raise RuntimeError("invalid definition")\n', RuntimeError, "invalid definition"),
        ("OTHER = 1\n", AttributeError, "PRESET"),
    ],
)
def test_invalid_preset_is_not_silently_skipped(tmp_path, monkeypatch, source, error, message):
    """无效定义必须阻止发现成功。"""
    monkeypatch.setattr(presets, "__file__", str(tmp_path / "__init__.py"))
    monkeypatch.setattr(presets, "__path__", [str(tmp_path)])
    (tmp_path / "test_invalid_role.py").write_text(source)
    invalidate_caches()
    with pytest.raises(error, match=message):
        presets.discover_agent_presets()


def test_duplicate_preset_slug_is_rejected(tmp_path, monkeypatch):
    """相同 slug 不能由后加载的角色覆盖。"""
    monkeypatch.setattr(presets, "__file__", str(tmp_path / "__init__.py"))
    monkeypatch.setattr(presets, "__path__", [str(tmp_path)])
    for name in ("test_duplicate_a", "test_duplicate_b"):
        (tmp_path / f"{name}.py").write_text(
            "from platform_core.agents.presets import AgentPreset\n"
            'PRESET = AgentPreset(slug="duplicate", name="重复", description="测试")\n'
        )
    invalidate_caches()
    with pytest.raises(ValueError, match="重复的预置 Agent slug: duplicate"):
        presets.discover_agent_presets()


def test_explicit_backend_ids_create_independent_instances():
    """后端工厂不共享可变实例状态。"""
    assert buildin.BUILTIN_BACKENDS == {
        "ChatbotAgent": ChatbotAgent,
        "SubAgentBackend": SubAgentBackend,
    }
    for backend_id, expected_type in buildin.BUILTIN_BACKENDS.items():
        first = buildin.get_agent_backend(backend_id)
        second = buildin.get_agent_backend(backend_id)
        assert type(first) is expected_type and type(second) is expected_type
        assert first is not second
        first.test_state = "first-run"
        assert not hasattr(second, "test_state")


def test_unregistered_backend_is_unavailable():
    """未知后端使用明确领域错误，供调用入口映射响应。"""
    with pytest.raises(buildin.AgentBackendNotFoundError, match="UnregisteredBackend"):
        buildin.get_agent_backend("UnregisteredBackend")


@pytest.mark.asyncio
async def test_backend_info_uses_registry_id_after_class_rename(monkeypatch):
    """类名改变不能影响公开的后端 ID。"""

    class RenamedBackend(ChatbotAgent):
        """使用不同 Python 类名模拟内部重命名。"""

    monkeypatch.setattr(buildin, "BUILTIN_BACKENDS", {"stable-backend-id": RenamedBackend})
    infos = await buildin.list_agent_backend_info()
    assert len(infos) == 1
    assert infos[0]["backend_id"] == "stable-backend-id"
    assert "id" not in infos[0]
    assert infos[0]["name"] == "智能助手"


def test_backend_import_does_not_scan_or_create_instances():
    """隔离进程中验证导入只声明能力，不扫描目录或创建后端。"""
    import subprocess

    code = """
from importlib import reload
from unittest.mock import patch
from platform_core.agents import buildin
with patch('pathlib.Path.iterdir', side_effect=AssertionError('directory scan')), \
     patch.object(buildin.ChatbotAgent, '__init__', side_effect=AssertionError('eager instance')):
    reload(buildin)
assert set(buildin.BUILTIN_BACKENDS) == {'ChatbotAgent', 'SubAgentBackend'}
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_id", ["ChatbotAgent", "SubAgentBackend"])
async def test_each_graph_uses_its_own_run_context(monkeypatch, backend_id):
    """实际编译并执行两个图，后一个运行不能复用前一个模型或上下文。"""
    from importlib import import_module
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    backend = buildin.get_agent_backend(backend_id)
    module = import_module(type(backend).__module__)
    monkeypatch.setattr(module, "sync_agent_context_skills", AsyncMock())
    monkeypatch.setattr(module, "resolve_configured_runtime_tools", AsyncMock(return_value=[]))
    monkeypatch.setattr(module, "_build_middlewares", AsyncMock(return_value=[]))
    monkeypatch.setattr(module, "create_agent_composite_backend", lambda _context: object())
    monkeypatch.setattr(module, "resolve_chat_model_spec", lambda spec: spec)
    monkeypatch.setattr(module, "build_prompt_with_context", lambda context: context.thread_id)
    monkeypatch.setattr(
        module,
        "load_chat_model",
        lambda fully_specified_name, session_id: FakeListChatModel(responses=[session_id]),
    )
    monkeypatch.setattr(backend, "_get_checkpointer", AsyncMock(return_value=None))
    graphs = []
    for thread_id in ["first-thread", "second-thread"]:
        context = SimpleNamespace(_runtime_prepared=True, model="test:model", thread_id=thread_id)
        graph = await backend.get_graph(context=context)
        result = await graph.ainvoke({"messages": [("user", "hello")]})
        assert result["messages"][-1].content == thread_id
        graphs.append(graph)
    assert graphs[0] is not graphs[1]


def test_shipping_skills_keep_required_dependencies():
    """默认知识能力及研究依赖不能因发现重组缺失。"""
    found = {spec["slug"]: spec for spec in skill_service.list_builtin_skill_specs()}
    assert set(found) == {
        "academic-evidence",
        "image-gen",
        "html-preview",
        "deep-research",
        "knowledge-base",
        "mysql-reporter",
        "equipment-research",
        "equipment-deep-conversation",
    }
    assert found["knowledge-base"]["tool_dependencies"] == [
        "list_kbs",
        "query_kb",
        "query_kbs",
        "find_kb_document",
        "open_kb_document",
        "get_mindmap",
        "search_file",
        "download_kb_file",
    ]
    assert found["deep-research"]["skill_dependencies"] == ["academic-evidence"]
    assert found["deep-research"]["tool_dependencies"] == [
        "web_search",
        "academic_search",
        "academic_get_papers",
        "academic_get_references",
        "present_artifacts",
    ]
    assert found["mysql-reporter"]["mcp_dependencies"] == []
    assert found["html-preview"]["version"] == "2026.10.15"
    assert found["equipment-research"]["tool_dependencies"] == ["start_equipment_research"]
    assert found["equipment-deep-conversation"]["tool_dependencies"] == [
        "equipment_deep_context",
        "save_equipment_capability_draft",
    ]


@pytest.mark.parametrize("slug", ["academic-evidence", "equipment-deep-conversation"])
def test_equipment_evidence_skills_preserve_autonomous_research(slug):
    """两个入口按需使用论文，不把研究限制为固定技术迁移模板。"""
    specs = {spec["slug"]: spec for spec in skill_service.list_builtin_skill_specs()}
    content = (specs[slug]["source_dir"] / "SKILL.md").read_text(encoding="utf-8")
    for requirement in (
        "以用户目标为主线",
        "不规定对话步骤、章节或固定推演链条",
        "不要求先有现成装备或已知技术瓶颈",
        "涉及技术实现且需要新证据、原理启发或可行性核实时",
        "不为每个构想强行匹配论文",
        "不要求逐项展开部件、迁移差距或验证方案",
        "取得或引用摘要不等于研究完成",
        "论文结论、类比迁移、工程推断和待验证假设",
        "装备级可用性",
        "不强套完整报告",
    ):
        assert requirement in content
    assert "论文已支持的机制 → 当前瓶颈 → 应用部件或分系统" not in content


def test_equipment_evidence_guidance_reaches_smart_and_deep_chat():
    """两个对话入口沿已有依赖加载学术证据规范，无需新增重复检索工具。"""
    found = {preset.slug: preset for preset in presets.discover_agent_presets()}
    specs = {spec["slug"]: spec for spec in skill_service.list_builtin_skill_specs()}
    assert found["default-chatbot"].context["preload_skills"] == ["deep-research", "academic-evidence"]
    assert "deep-research" in found["deep-research"].context["preload_skills"]
    assert "academic-evidence" in specs["deep-research"]["skill_dependencies"]
    content = (specs["deep-research"]["source_dir"] / "SKILL.md").read_text(encoding="utf-8")
    assert "任务未明确要求固定过程时，不套用固定章节" in content
    assert "优先通过 `subagent_start`" in content
    assert "Project 沙盒" in content
    assert "取消、检查点" in content
    assert "恢复依据" in content
    assert "固定业务流水线" not in content


def test_specialized_equipment_skill_keeps_equipment_identity_gate():
    """专用装备技能保留装备身份约束，通用深研技能不复制该流程。"""
    specs = {spec["slug"]: spec for spec in skill_service.list_builtin_skill_specs()}
    content = (specs["equipment-deep-conversation"]["source_dir"] / "SKILL.md").read_text(encoding="utf-8")

    assert "S3/S4" in content
    assert "物理武器实体" in content
    assert "直接打击、毁伤、压制、拦截或拒止具体作战对象" in content
    assert "可观察直接战果" in content
    assert "只能作为装备分系统或支撑条件" in content
    assert "技术方案在推演中形成、重构、替换武器装备" in content
    assert "具体作战制胜新质武器" in content
    assert "不得先形成抽象技术方案" in content


def test_generic_deep_research_has_no_fixed_winning_lens_count():
    """通用深研根据证据缺口决定分片，不固化三加一制胜视角。"""
    specs = {spec["slug"]: spec for spec in skill_service.list_builtin_skill_specs()}
    content = (specs["deep-research"]["source_dir"] / "SKILL.md").read_text(encoding="utf-8")

    for requirement in (
        "正交问题",
        "并行度根据任务规模",
        "先小规模探索查询质量",
        "空结果或低相关分支及时停止",
    ):
        assert requirement in content
    assert "3 个正交" not in content
    assert "第 4 个" not in content


def test_generic_research_can_handoff_to_existing_equipment_chain_at_convergence():
    """附件任务按目标在后段复用装备链，而不是创建任务书专用流程。"""

    found = {preset.slug: preset for preset in presets.discover_agent_presets()}
    specs = {spec["slug"]: spec for spec in skill_service.list_builtin_skill_specs()}
    policy = found["default-chatbot"].context["system_prompt"]
    content = (specs["deep-research"]["source_dir"] / "SKILL.md").read_text(encoding="utf-8")

    for requirement in (
        "通用研究能力",
        "正式 S1–S6 研究",
        "能力画像",
        "完整装备研发技术方案",
        "后段链路",
        "equipment-research",
    ):
        assert requirement in policy
    for requirement in (
        "与装备研究能力衔接",
        "start_equipment_research",
        "后段链路",
        "是否衔接、衔接时点和起始层级",
        "只要求技术清单、科学问题、专业方向或一般研究",
    ):
        assert requirement in content
    assert "任务书专用" not in policy
    assert "任务书专用" not in content


@pytest.mark.parametrize(
    "registered_tool",
    [start_equipment_research, equipment_deep_context, save_equipment_capability_draft],
)
def test_equipment_tools_declare_injectable_runtime(registered_tool):
    """LangGraph only injects runtime state when the annotation is ToolRuntime itself."""
    assert get_type_hints(registered_tool.coroutine)["runtime"] is ToolRuntime
