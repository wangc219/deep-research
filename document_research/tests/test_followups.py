"""Explicit, bounded follow-ups with fresh retrieval and revocable user context."""

import asyncio
import copy
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from document_research.config import init_config, load_config
from document_research.service import PREFIX, create_app

ALICE = "synthetic-followup-alice-token-at-least-24"
BOB = "synthetic-followup-bob-token-at-least-24"


class ContextEngine:
    def __init__(self):
        self.seen = []
        self.started = threading.Event()
        self.release = threading.Event()
        self.release.set()

    def is_configured(self):
        return True

    async def respond(self, kind, task, sources, authorize):
        authorize()
        self.seen.append((kind, copy.deepcopy(task), copy.deepcopy(sources)))
        self.started.set()
        while not self.release.is_set():
            await asyncio.sleep(0.01)
        authorize()
        return {"sources": sources, "summary": "synthetic report", "assumptions": []}

    async def run(self, task, sources, authorize):
        return await self.respond("run", task, sources, authorize)

    async def retrieve(self, task, sources, authorize):
        return await self.respond("retrieve", task, sources, authorize)


@pytest.fixture
def setup(tmp_path):
    init_config(tmp_path)
    config = load_config(tmp_path)
    config.update(
        tokens={"alice": ALICE, "bob": BOB},
        zhipu={"api_key": "synthetic", "libraries": {"alice": [{"id": "fixture"}]}},
    )
    (tmp_path / "config.json").write_text(json.dumps(config))
    engine = ContextEngine()
    app = create_app(tmp_path, engine)
    with TestClient(app, headers={"Authorization": "Bearer " + ALICE}) as client:
        yield client, app.state.store, engine, tmp_path


def create(client, **changes):
    body = {
        "problem": "文档表格解析要求",
        "mode": "answer",
        "allow_external_model": True,
    }
    body.update(changes)
    response = client.post(PREFIX + "/tasks", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def wait_completed(client, task):
    for _ in range(100):
        response = client.get(f"{PREFIX}/tasks/{task['id']}")
        if response.status_code == 200 and response.json()["status"] == "completed":
            return response.json()
        time.sleep(0.01)
    pytest.fail(f"did not complete: {response.status_code} {response.text}")


def complete(client, **changes):
    task = create(client, **changes)
    assert client.post(f"{PREFIX}/tasks/{task['id']}/run").status_code == 202
    return wait_completed(client, task)


def library(client):
    response = client.post(PREFIX + "/libraries", json={"name": "Synthetic context"})
    assert response.status_code == 201
    return response.json()["id"]


def upload(client, library_id):
    response = client.post(
        f"{PREFIX}/libraries/{library_id}/documents",
        files={"file": ("sample.txt", "合成表格需求，不是实验结果。".encode())},
    )
    assert response.status_code == 201
    return response.json()


def followup_body(parent, **changes):
    body = {
        "parent_task_id": parent["id"],
        "problem": "如何验证这个问题？",
        "library_ids": parent["library_ids"],
    }
    body.update(changes)
    return body


def test_no_parent_means_no_implicit_history(setup):
    client, _, engine, _ = setup
    complete(client, problem="上一轮私有问题")
    fresh = create(client, problem="新问题")
    assert fresh["parent_task_id"] is None
    assert fresh["context_questions"] == []
    assert fresh["context_truncated"] is False
    assert "context_task_ids" not in fresh
    response = client.post(PREFIX + "/retrieve", json={"problem": "新问题"})
    assert response.status_code == 200
    assert engine.seen[-1][1]["context_questions"] == []


def test_followup_inherits_only_user_questions_not_answer_or_consent(setup):
    client, store, engine, _ = setup
    parent = complete(
        client,
        problem="合并单元格识别失败",
        allow_public=True,
        allow_web_search=True,
        public_query="Docling public-only",
        constraints="上一轮私有约束",
    )
    stored = store.task(parent["id"])
    stored["report"] = {"summary": "PRIVATE_MODEL_ANSWER_NOT_CONTEXT"}
    store.save_task(stored)
    child = create(
        client, **followup_body(parent), allow_external_model=False, mode="research"
    )
    assert child["context_questions"] == [parent["problem"]]
    assert child["context_truncated"] is False
    assert child["allow_external_model"] is False
    assert child["allow_public"] is False and child["allow_web_search"] is False
    assert child["public_query"] == "" and child["constraints"] == ""
    assert child["report"] is None and child["status"] == "needs_input"
    assert "context_task_ids" not in child
    assert "PRIVATE_MODEL_ANSWER_NOT_CONTEXT" not in json.dumps(child)
    response = client.post(PREFIX + "/retrieve", json=followup_body(parent))
    assert response.status_code == 200
    assert response.json()["context_questions"] == [parent["problem"]]
    assert response.json()["context_truncated"] is False
    assert engine.seen[-1][0] == "retrieve"
    assert "PRIVATE_MODEL_ANSWER_NOT_CONTEXT" not in json.dumps(engine.seen[-1])
    assert engine.seen[-1][1]["allow_web_search"] is False


def test_depth_and_length_are_bounded_with_disclosed_truncation(setup):
    client, store, _, _ = setup
    previous = complete(client, problem="甲" * 2500)
    expected = [previous["problem"][:2000]]
    for index in range(5):
        previous = complete(
            client,
            **followup_body(previous, problem=f"第 {index} 轮追问"),
        )
        assert previous["context_questions"] == expected[-3:]
        assert previous["context_truncated"] is True
        assert len(store.task(previous["id"])["context_task_ids"]) <= 3
        expected.append(previous["problem"])
    assert previous["context_questions"] == [
        "第 1 轮追问",
        "第 2 轮追问",
        "第 3 轮追问",
    ]


def test_retention_cap_alone_sets_truncation(setup):
    client, _, _, _ = setup
    parent = complete(client, problem="第一轮")
    for index in range(4):
        parent = complete(client, **followup_body(parent, problem=f"追问 {index}"))
        assert parent["context_truncated"] is (index == 3)


@pytest.mark.parametrize("endpoint", ["/tasks", "/retrieve"])
@pytest.mark.parametrize(
    "injected",
    [
        {"context_questions": ["injected"]},
        {"context_task_ids": ["other"]},
        {"context_truncated": False},
        {"parent_task_id": " "},
        {"parent_task_id": "x" * 101},
    ],
)
def test_caller_cannot_supply_history_or_invalid_parent_id(setup, endpoint, injected):
    client, _, _, _ = setup
    response = client.post(PREFIX + endpoint, json={"problem": "新问题", **injected})
    assert response.status_code == 422


@pytest.mark.parametrize("endpoint", ["/tasks", "/retrieve"])
def test_parent_must_exist_and_belong_to_caller(setup, endpoint):
    client, _, _, _ = setup
    parent = complete(client)
    response = client.post(
        PREFIX + endpoint,
        json=followup_body(parent),
        headers={"Authorization": "Bearer " + BOB},
    )
    assert response.status_code == 404
    response = client.post(
        PREFIX + endpoint,
        json=followup_body(parent, parent_task_id="missing"),
    )
    assert response.status_code == 404


@pytest.mark.parametrize(
    "status", ["needs_input", "ready", "running", "cancelled", "failed"]
)
@pytest.mark.parametrize("endpoint", ["/tasks", "/retrieve"])
def test_parent_must_be_completed(setup, status, endpoint):
    client, store, _, _ = setup
    parent = create(client)
    persisted = store.task(parent["id"])
    persisted["status"] = status
    store.save_task(persisted)
    response = client.post(PREFIX + endpoint, json=followup_body(parent))
    assert response.status_code == 409


def test_same_library_set_can_be_reordered_but_not_changed(setup):
    client, _, _, _ = setup
    first, second, third = library(client), library(client), library(client)
    parent = complete(client, library_ids=[first, second])
    reordered = create(client, **followup_body(parent, library_ids=[second, first]))
    assert reordered["context_questions"] == [parent["problem"]]
    for endpoint in ["/tasks", "/retrieve"]:
        response = client.post(
            PREFIX + endpoint, json=followup_body(parent, library_ids=[third])
        )
        assert response.status_code == 409


@pytest.mark.parametrize("change", ["upload", "delete_document", "delete_library"])
def test_evidence_change_invalidates_parent_and_existing_child(setup, change):
    client, _, _, _ = setup
    selected = library(client)
    document = upload(client, selected)
    parent = complete(client, library_ids=[selected])
    child = create(client, **followup_body(parent))
    if change == "upload":
        upload(client, selected)
    elif change == "delete_document":
        assert client.delete(f"{PREFIX}/documents/{document['id']}").status_code == 200
    else:
        assert client.delete(f"{PREFIX}/libraries/{selected}").status_code == 200
    assert client.get(f"{PREFIX}/tasks/{child['id']}").status_code == 403
    assert client.post(f"{PREFIX}/tasks/{child['id']}/run").status_code == 403
    assert client.patch(f"{PREFIX}/tasks/{child['id']}", json={}).status_code == 403
    for endpoint in ["/tasks", "/retrieve"]:
        assert (
            client.post(PREFIX + endpoint, json=followup_body(parent)).status_code
            == 403
        )


def test_remote_grant_revocation_invalidates_context(setup):
    client, _, _, path = setup
    parent = complete(client, library_ids=["zhipu:fixture"])
    child = create(client, **followup_body(parent))
    config = load_config(path)
    config["zhipu"]["libraries"]["alice"] = []
    (path / "config.json").write_text(json.dumps(config))
    assert client.get(f"{PREFIX}/tasks/{child['id']}").status_code == 403
    assert client.post(f"{PREFIX}/tasks/{child['id']}/run").status_code == 403
    assert (
        client.post(PREFIX + "/retrieve", json=followup_body(parent)).status_code == 403
    )


@pytest.mark.parametrize("change", ["delete", "edit", "owner"])
def test_retained_ancestor_is_rechecked_even_when_immediate_parent_is_complete(
    setup, change
):
    client, store, _, _ = setup
    ancestor = complete(client)
    parent = complete(client, **followup_body(ancestor))
    child = create(client, **followup_body(parent))
    if change == "delete":
        with store.connection() as db:
            db.execute("DELETE FROM tasks WHERE id=?", (ancestor["id"],))
    elif change == "edit":
        assert (
            client.patch(f"{PREFIX}/tasks/{ancestor['id']}", json={}).status_code == 200
        )
    else:
        persisted = store.task(ancestor["id"])
        persisted["owner"] = "bob"
        store.save_task(persisted)
    assert store.task(parent["id"])["status"] == "completed"
    assert client.get(f"{PREFIX}/tasks/{child['id']}").status_code == 403
    assert client.post(f"{PREFIX}/tasks/{child['id']}/run").status_code == 403
    assert (
        client.post(PREFIX + "/retrieve", json=followup_body(parent)).status_code == 403
    )


def test_followup_runs_with_fresh_collection_and_remains_cancellable(setup):
    client, store, engine, _ = setup
    selected = library(client)
    document = upload(client, selected)
    parent = complete(client, library_ids=[selected])
    persisted = store.task(parent["id"])
    persisted["report"]["sources"] = [{"text": "old model evidence must not be reused"}]
    store.save_task(persisted)
    child = create(client, **followup_body(parent))
    engine.release.clear()
    engine.started.clear()
    assert client.post(f"{PREFIX}/tasks/{child['id']}/run").status_code == 202
    assert engine.started.wait(1)
    assert engine.seen[-1][1]["context_questions"] == [parent["problem"]]
    assert engine.seen[-1][2][0]["document_id"] == document["id"]
    assert "old model evidence" not in json.dumps(engine.seen[-1])
    assert client.post(f"{PREFIX}/tasks/{child['id']}/cancel").status_code == 200
    engine.release.set()
    assert client.get(f"{PREFIX}/tasks/{child['id']}").json()["status"] == "cancelled"


def test_running_child_discards_result_when_parent_becomes_unavailable(setup):
    client, store, engine, _ = setup
    parent = complete(client)
    child = create(client, **followup_body(parent))
    engine.release.clear()
    engine.started.clear()
    assert client.post(f"{PREFIX}/tasks/{child['id']}/run").status_code == 202
    assert engine.started.wait(1)
    assert client.patch(f"{PREFIX}/tasks/{parent['id']}", json={}).status_code == 200
    engine.release.set()
    for _ in range(100):
        persisted = store.task(child["id"])
        if persisted["status"] == "failed":
            break
        time.sleep(0.01)
    assert persisted["status"] == "failed" and persisted["report"] is None
    assert client.get(f"{PREFIX}/tasks/{child['id']}").status_code == 403


def test_preview_discards_result_after_parent_changes_during_retrieval(setup):
    client, _, engine, _ = setup
    parent = complete(client)
    engine.release.clear()
    engine.started.clear()
    with ThreadPoolExecutor() as executor:
        future = executor.submit(
            client.post, PREFIX + "/retrieve", json=followup_body(parent)
        )
        assert engine.started.wait(1)
        assert (
            client.patch(f"{PREFIX}/tasks/{parent['id']}", json={}).status_code == 200
        )
        engine.release.set()
        response = future.result(timeout=2)
    assert response.status_code == 403
