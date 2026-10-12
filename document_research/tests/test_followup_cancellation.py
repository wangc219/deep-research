"""Cancellation remains available to the owner without releasing stale evidence."""

import asyncio
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from document_research.config import init_config, load_config
from document_research.service import PREFIX, create_app

ALICE = "synthetic-cancellation-alice-token-at-least-24"
BOB = "synthetic-cancellation-bob-token-at-least-24"


class CancellableEngine:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.cancelled = threading.Event()
        self.release.set()

    def is_configured(self):
        return True

    async def run(self, task, sources, authorize):
        authorize()
        self.started.set()
        try:
            while not self.release.is_set():
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        authorize()
        return {"assumptions": [], "sources": sources, "summary": "private report"}


@pytest.fixture
def running_child(tmp_path):
    init_config(tmp_path)
    config = load_config(tmp_path)
    config.update(
        tokens={"alice": ALICE, "bob": BOB},
        zhipu={"api_key": "synthetic", "libraries": {"alice": [{"id": "fixture"}]}},
    )
    (tmp_path / "config.json").write_text(json.dumps(config))
    engine = CancellableEngine()
    app = create_app(tmp_path, engine)
    with TestClient(app, headers={"Authorization": "Bearer " + ALICE}) as client:
        library = client.post(
            PREFIX + "/libraries", json={"name": "private library"}
        ).json()
        scope = [library["id"], "zhipu:fixture"]
        parent = client.post(
            PREFIX + "/tasks",
            json={
                "mode": "answer",
                "problem": "PRIVATE PARENT QUESTION",
                "library_ids": scope,
                "allow_external_model": True,
            },
        ).json()
        assert client.post(f"{PREFIX}/tasks/{parent['id']}/run").status_code == 202
        for _ in range(100):
            if app.state.store.task(parent["id"])["status"] == "completed":
                break
            time.sleep(0.01)
        assert app.state.store.task(parent["id"])["status"] == "completed"
        child = client.post(
            PREFIX + "/tasks",
            json={
                "mode": "answer",
                "problem": "PRIVATE CHILD QUESTION",
                "library_ids": scope,
                "parent_task_id": parent["id"],
                "allow_external_model": True,
            },
        ).json()
        engine.release.clear()
        engine.started.clear()
        assert client.post(f"{PREFIX}/tasks/{child['id']}/run").status_code == 202
        assert engine.started.wait(1)
        yield client, app.state.store, engine, tmp_path, library, parent, child
        engine.release.set()


@pytest.mark.parametrize(
    "change", ["upload", "delete_library", "parent_edit", "remote_revoke"]
)
def test_owner_can_cancel_stale_followup_without_receiving_old_context(
    running_child, change
):
    client, store, engine, path, library, parent, child = running_child
    if change == "upload":
        response = client.post(
            f"{PREFIX}/libraries/{library['id']}/documents",
            files={"file": ("synthetic.txt", b"New synthetic document")},
        )
        assert response.status_code == 201
    elif change == "delete_library":
        assert client.delete(f"{PREFIX}/libraries/{library['id']}").status_code == 200
    elif change == "parent_edit":
        assert (
            client.patch(f"{PREFIX}/tasks/{parent['id']}", json={}).status_code == 200
        )
    else:
        config = load_config(path)
        config["zhipu"]["libraries"]["alice"] = []
        (path / "config.json").write_text(json.dumps(config))

    assert client.get(f"{PREFIX}/tasks/{child['id']}").status_code == 403
    response = client.post(f"{PREFIX}/tasks/{child['id']}/cancel")
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "id": child["id"],
        "status": "cancelled",
        "mode": "answer",
        "library_ids": [],
        "problem": "资料权限或内容已变更，已取消本地等待与结果输出。",
        "questions": [],
        "assumptions": [],
        "context_questions": [],
        "report": None,
        "scope_invalidated": True,
    }
    assert "PRIVATE" not in response.text
    assert library["id"] not in response.text and parent["id"] not in response.text
    assert engine.cancelled.wait(1)
    assert store.task(child["id"])["status"] == "cancelled"
    assert store.task(child["id"])["report"] is None
    # Cancellation grants no read/restart access and is not a stale task viewer.
    assert client.get(f"{PREFIX}/tasks/{child['id']}").status_code == 403
    assert client.post(f"{PREFIX}/tasks/{child['id']}/run").status_code == 403
    assert client.post(f"{PREFIX}/tasks/{child['id']}/cancel").status_code == 403


@pytest.mark.parametrize("caller", ["other_owner", "revoked_token"])
def test_cancellation_exception_never_bypasses_identity_or_ownership(
    running_child, caller
):
    client, store, engine, path, library, _, child = running_child
    assert client.delete(f"{PREFIX}/libraries/{library['id']}").status_code == 200
    if caller == "revoked_token":
        config = load_config(path)
        config["tokens"]["alice"] = "synthetic-replacement-alice-token-at-least-24"
        (path / "config.json").write_text(json.dumps(config))
        headers = {"Authorization": "Bearer " + ALICE}
        expected_status = 401
    else:
        headers = {"Authorization": "Bearer " + BOB}
        expected_status = 404
    response = client.post(f"{PREFIX}/tasks/{child['id']}/cancel", headers=headers)
    assert response.status_code == expected_status
    assert "PRIVATE" not in response.text
    assert store.task(child["id"])["status"] == "running"
    assert not engine.cancelled.is_set()


def test_current_scope_cancellation_retains_normal_task_response(running_child):
    client, store, engine, _, library, _, child = running_child
    response = client.post(f"{PREFIX}/tasks/{child['id']}/cancel")
    assert response.status_code == 200
    assert response.json()["problem"] == "PRIVATE CHILD QUESTION"
    assert library["id"] in response.json()["library_ids"]
    assert "scope_invalidated" not in response.json()
    assert response.json()["context_questions"] == ["PRIVATE PARENT QUESTION"]
    assert engine.cancelled.wait(1)
    assert store.task(child["id"])["status"] == "cancelled"
