"""本地 Pilot 账号和知识库准备脚本的权限回归测试。"""

from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "provision_knowledge_graph_pilot.py"
SPEC = importlib.util.spec_from_file_location("provision_knowledge_graph_pilot", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_annotation_accounts_receive_read_only_knowledge_base_access():
    """标注员和仲裁专家不得获得知识库管理权限。"""

    account_uids = ["annotator-a", "annotator-b", "arbitrator"]
    config = MODULE._pilot_share_config(account_uids)

    assert config == {
        "version": 2,
        "read_scope": {"access_level": "user", "user_uids": account_uids},
        "manage_scope": None,
    }
