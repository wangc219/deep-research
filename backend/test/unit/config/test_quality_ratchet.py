"""质量基线不能用总量下降掩盖新增问题。"""

from collections import Counter
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
if not (ROOT / "scripts/check_backend_quality.py").is_file():
    pytest.skip("质量门禁测试需要完整仓库脚本；CI 在仓库根运行此测试", allow_module_level=True)

spec = importlib.util.spec_from_file_location("backend_quality_gate", ROOT / "scripts/check_backend_quality.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_new_problem_is_rejected_even_when_total_decreases():
    """总量下降不能抵消新增错误。"""
    baseline = Counter({"old-a": 2, "old-b": 1})
    current = Counter({"old-a": 1, "new-critical": 1})
    new, resolved = module.compare_findings(current, baseline)
    assert new == Counter({"new-critical": 1})
    assert resolved == Counter({"old-a": 1, "old-b": 1})


def test_duplicate_new_issue_cannot_hide_in_existing_fingerprint():
    """已有诊断重复增加也必须被识别。"""
    new, resolved = module.compare_findings(Counter({"same": 2}), Counter({"same": 1}))
    assert new == Counter({"same": 1}) and not resolved


def test_moving_existing_source_line_does_not_create_a_new_finding(tmp_path):
    """仅移动源代码行时保持基线身份。"""
    source = tmp_path / "example.py"
    source.write_text("value = 1\n")
    issue = {"filename": str(source), "code": "E501", "message": "long", "location": {"row": 1}}
    before = module.fingerprints([issue], tmp_path)
    source.write_text("\nvalue = 1\n")
    issue["location"]["row"] = 2
    after = module.fingerprints([issue], tmp_path)
    assert before == after
