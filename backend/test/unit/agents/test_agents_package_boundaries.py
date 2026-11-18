from __future__ import annotations

import subprocess
import sys


def test_agents_package_does_not_eagerly_import_runtime_toolkits() -> None:
    script = """
import sys
import platform_core.agents

assert 'platform_core.agents.toolkits' not in sys.modules
assert 'platform_core.agents.toolkits.buildin.tools' not in sys.modules
assert 'public_web_search_gateway' not in sys.modules

from platform_core.agents.skills.repository import SkillRepository
assert SkillRepository.__name__ == 'SkillRepository'
assert 'public_web_search_gateway' not in sys.modules
"""
    subprocess.run([sys.executable, "-c", script], check=True)


def test_public_agent_exports_remain_available() -> None:
    from platform_core.agents import BaseAgent, BaseContext, BaseState

    assert BaseAgent.__name__ == "BaseAgent"
    assert BaseContext.__name__ == "BaseContext"
    assert BaseState.__name__ == "BaseState"
