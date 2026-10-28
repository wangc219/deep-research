import os
from pathlib import Path
import stat
import subprocess

import pytest
import yaml


def _project_root() -> Path:
    """定位包含 Compose 文件的仓库根目录。"""
    configured = os.environ.get("DEEP_RESEARCH_PROJECT_ROOT")
    if configured:
        return Path(configured)

    for parent in Path(__file__).resolve().parents:
        if (parent / "compose.yaml").exists():
            return parent
    pytest.skip("当前测试环境未挂载仓库根目录")


def test_compose_does_not_expose_checkpoint_backend_or_local_storage():
    """LangGraph checkpoint 固定使用 PostgreSQL，不保留本地后端配置面。"""
    project_root = _project_root()
    for filename in ("compose.yaml", "compose.prod.yaml"):
        compose = yaml.safe_load((project_root / filename).read_text())
        assert "LANGGRAPH_CHECKPOINTER_BACKEND" not in compose["x-api-worker-env"]
        assert "DEEP_RESEARCH_CHECKPOINT_DIR" not in compose["x-api-worker-env"]


def test_api_key_derivation_secret_is_required_for_api_and_worker():
    project_root = _project_root()
    for filename in ("compose.yaml", "compose.prod.yaml"):
        compose = yaml.safe_load((project_root / filename).read_text())
        configured = compose["x-api-worker-env"]["API_KEY_DERIVATION_SECRET"]

        assert configured.startswith("${API_KEY_DERIVATION_SECRET:?")


def test_initialization_scripts_enforce_security_secret_contract():
    project_root = _project_root()
    shell_script = project_root / "scripts/init.sh"

    assert shell_script.stat().st_mode & stat.S_IXUSR
    assert "--validate-security-env" in shell_script.read_text()
    assert "umask 077" in shell_script.read_text()
    assert "validate_security_env" in shell_script.read_text()
    assert "security_secret_is_valid" in shell_script.read_text()


@pytest.mark.parametrize(
    "overrides",
    [
        {"API_KEY_DERIVATION_SECRET": "short"},
        {"API_KEY_DERIVATION_SECRET": "jwt-secret-value-that-is-at-least-32-characters"},
        {"SANDBOX_PROVISIONER_TOKEN": "api-secret-value-that-is-at-least-32-characters"},
        {"JWT_SECRET_KEY": " padded-secret-value-that-is-at-least-32-characters "},
        {"JWT_SECRET_KEY": '"123456789012345678901234567890"'},
    ],
)
def test_shell_initialization_validation_rejects_short_reused_or_padded_secrets(
    tmp_path: Path, overrides: dict, monkeypatch
):
    monkeypatch.delenv("DEEP_RESEARCH_ENV_FILE", raising=False)
    project_root = _project_root()
    values = {
        "JWT_SECRET_KEY": "jwt-secret-value-that-is-at-least-32-characters",
        "API_KEY_DERIVATION_SECRET": "api-secret-value-that-is-at-least-32-characters",
        "SANDBOX_PROVISIONER_TOKEN": "sandbox-secret-value-that-is-at-least-32-characters",
        **overrides,
    }
    (tmp_path / ".env").write_text("".join(f"{name}={value}\n" for name, value in values.items()))

    completed = subprocess.run(
        ["bash", str(project_root / "scripts/init.sh"), "--validate-security-env"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0


def test_shell_initialization_validation_accepts_distinct_strong_secrets(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("DEEP_RESEARCH_ENV_FILE", raising=False)
    project_root = _project_root()
    (tmp_path / ".env").write_text(
        "JWT_SECRET_KEY=jwt-secret-value-that-is-at-least-32-characters\n"
        "API_KEY_DERIVATION_SECRET=api-secret-value-that-is-at-least-32-characters\n"
        "SANDBOX_PROVISIONER_TOKEN=sandbox-secret-value-that-is-at-least-32-characters\n"
    )

    completed = subprocess.run(
        ["bash", str(project_root / "scripts/init.sh"), "--validate-security-env"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_backend_unit_workflow_runs_for_initialization_contract_changes():
    project_root = _project_root()
    workflow = yaml.load((project_root / ".github/workflows/quality.yml").read_text(), Loader=yaml.BaseLoader)
    for event in ("pull_request", "push"):
        # 无路径过滤，初始化脚本和环境示例的变更都会执行配置契约测试。
        assert event in workflow["on"]
        assert not (workflow["on"][event] or {}).get("paths")
    commands = [step.get("run", "") for step in workflow["jobs"]["python"]["steps"]]
    assert any("backend/test/unit/config" in command for command in commands)


def test_api_healthcheck_uses_readiness_in_development_and_production():
    """Compose 调度只能在核心依赖就绪后把 API 标记为 healthy。"""
    project_root = _project_root()
    for filename in ("compose.yaml", "compose.prod.yaml"):
        compose = yaml.safe_load((project_root / filename).read_text())

        assert compose["services"]["api"]["healthcheck"]["test"] == [
            "CMD-SHELL",
            "curl -f http://localhost:5050/api/system/ready || exit 1",
        ]


def test_worker_healthcheck_uses_arq_health_contract_in_development_and_production():
    project_root = _project_root()
    for filename in ("compose.yaml", "compose.prod.yaml"):
        compose = yaml.safe_load((project_root / filename).read_text())

        healthcheck = compose["services"]["worker"]["healthcheck"]["test"]
        if healthcheck[0] == "CMD-SHELL":
            import shlex
            command = shlex.split(healthcheck[1])
        else:
            assert healthcheck[0] == "CMD"
            command = healthcheck[1:]
        assert command[-3:] == ["arq", "--check", "server.worker_main.WorkerSettings"]


def test_worker_starts_owned_entrypoint_in_development_and_production():
    """正式部署必须进入拥有本地任务过滤的 Worker 入口。"""
    project_root = _project_root()
    for filename in ("compose.yaml", "compose.prod.yaml"):
        compose = yaml.safe_load((project_root / filename).read_text())
        assert "python -m server.worker_main" in compose["services"]["worker"]["command"]


def test_arq_dependency_changes_trigger_real_dispatch_regression():
    """单独升级依赖也必须触发拥有 ARQ 适配语义的真实 Redis gate。"""
    project_root = _project_root()
    workflow = yaml.load((project_root / ".github/workflows/quality.yml").read_text(), Loader=yaml.BaseLoader)
    for event in ("pull_request", "push"):
        assert event in workflow["on"]
        assert not (workflow["on"][event] or {}).get("paths")
    job = workflow["jobs"]["redis-dispatch"]
    assert job["services"]["redis"]["image"].startswith("redis:")
    assert any("test_arq_worker_dispatch.py" in step.get("run", "") for step in job["steps"])
