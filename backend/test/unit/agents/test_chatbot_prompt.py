from types import SimpleNamespace

from platform_core.agents.buildin.chatbot.prompt import PROMPT, build_prompt_with_context


def test_chatbot_prompt_prefers_complete_explanatory_paragraphs():
    assert "减少 bullet points" in PROMPT
    assert "完整的句子和段落" in PROMPT
    assert "详细的解释和背景信息" in PROMPT


def test_chatbot_prompt_declares_workspace_visibility_and_default_write_boundary():
    prompt = build_prompt_with_context(
        SimpleNamespace(
            workdir_path="/home/gem/user-data/projects/11111111-1111-4111-8111-111111111111",
            system_prompt="",
        )
    )

    assert "可以读取其他 Project 目录作为参考" in prompt
    assert "未经用户明确要求，不得在当前 Project Workdir 之外" in prompt
    assert "/home/gem/user-data/agents/skills/" in prompt
    assert "html:preview" not in prompt


def test_subagent_returns_real_files_for_parent_delivery():
    """子智能体不应被提示调用运行时明确禁用的交付工具。"""
    prompt = build_prompt_with_context(
        SimpleNamespace(workdir_path="/home/gem/user-data/projects/deep", system_prompt="", is_subagent_runtime=True)
    )
    assert "向主智能体返回真实文件绝对路径与摘要" in prompt
    assert "再调用 present_artifacts 登记绝对路径" not in prompt
