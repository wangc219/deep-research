"""模型管理与任务交付的权限、持久化和并发验收。"""

import io
import json
import stat
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from document_research.config import init_config, load_config
from document_research.deliveries import MAX_DELIVERY_BYTES, NAMES, Deliveries, digest
from document_research.service import PREFIX, create_app
from document_research.storage import Store
from document_research.tests.test_service import (
    ALICE,
    BOB,
    SyntheticEngine,
    configure,
    task,
)


@pytest.fixture
def environment(tmp_path):
    init_config(tmp_path)
    configure(tmp_path, tokens={"alice": ALICE, "bob": BOB}, settings_admins=["alice"])
    app = create_app(tmp_path, SyntheticEngine())
    with TestClient(app, headers={"Authorization": "Bearer " + ALICE}) as client:
        yield client, tmp_path, app


def completed(environment):
    client, _, app = environment
    item = task(client)
    stored = app.state.store.task(item["id"])
    stored.update(
        status="completed",
        report={
            "summary": "<script>alert('secret')</script>",
            "sources": [
                {"id": "s1", "title": "=HYPERLINK(1)", "text": "evidence", "page": 1}
            ],
        },
    )
    app.state.store.save_task(stored)
    return stored


def model_body(**changes):
    return {
        "base_url": "http://127.0.0.1:4298/v1",
        "model": "synthetic",
        "api_key": "private-key",
        **changes,
    }


def test_settings_secret_preservation_and_clear(environment):
    client, directory, _ = environment
    url = PREFIX + "/settings/model"
    response = client.put(url, json=model_body())
    assert response.status_code == 200
    assert response.json()["has_api_key"] is True
    assert "private-key" not in response.text + client.get(url).text
    assert stat.S_IMODE((directory / "config.json").stat().st_mode) == 0o600
    assert (
        client.put(url, json=model_body(api_key="", model="new-model")).status_code
        == 200
    )
    assert load_config(directory)["model"]["api_key"] == "private-key"
    assert (
        client.put(url, json=model_body(api_key="", clear_api_key=True)).json()[
            "model_configured"
        ]
        is False
    )
    assert load_config(directory)["tokens"]["bob"] == BOB
    assert not list(directory.glob(".config-*"))


@pytest.mark.parametrize(
    "changes",
    [
        {"base_url": "http://example.com/v1"},
        {"base_url": "https://user:private-key@example.com/v1"},
        {"base_url": "https://example.com/v1?key=private-key"},
        {"model": " "},
        {"reasoning_effort": "medium"},
        {"clear_api_key": True},
        {"api_key": "private-key\ninvalid"},
    ],
)
def test_settings_reject_invalid_inputs_without_secret_echo(environment, changes):
    client, directory, _ = environment
    previous = load_config(directory)
    response = client.put(PREFIX + "/settings/model", json=model_body(**changes))
    assert response.status_code == 422
    assert "private-key" not in response.text
    assert load_config(directory) == previous


def test_non_admin_and_revocation(environment):
    client, directory, _ = environment
    url = PREFIX + "/settings/model"
    for method in ("GET", "PUT"):
        response = client.request(
            method,
            url,
            headers={"Authorization": "Bearer " + BOB},
            **({"json": model_body()} if method == "PUT" else {}),
        )
        assert response.status_code == 403
    configure(directory, settings_admins=[])
    assert client.put(url, json=model_body()).status_code == 403
    configure(directory, tokens={"bob": BOB})
    assert client.get(url).status_code == 401


def test_delivery_exports_edits_bundle_and_restart(environment):
    client, directory, _ = environment
    item = completed(environment)
    base = f"{PREFIX}/tasks/{item['id']}"
    assert [
        value["name"] for value in client.get(base + "/artifacts").json()["items"]
    ] == list(NAMES)
    content = client.get(base + "/artifacts/report.html/download").text
    assert "<script>alert" not in content and "&lt;script&gt;" in content
    csv = client.get(base + "/artifacts/evidence.csv/download").text
    assert "'=HYPERLINK" in csv
    original = client.get(base + "/artifacts/report.md").json()
    edit = {"content": "# edited delivery", "expected_sha256": original["sha256"]}
    assert client.put(base + "/artifacts/report.md", json=edit).status_code == 200
    assert client.put(base + "/artifacts/report.md", json=edit).status_code == 409
    reopened = Deliveries(Store(directory)).files(item)
    assert reopened["report.md"] == edit["content"]
    archive = zipfile.ZipFile(io.BytesIO(client.get(base + "/delivery.zip").content))
    assert archive.namelist() == list(NAMES)
    assert archive.read("report.md").decode() == edit["content"]
    assert (
        json.loads(archive.read("report.json"))["summary"] == item["report"]["summary"]
    )
    assert client.get(base + "/artifacts/config.json").status_code == 404
    assert client.put(base + "/artifacts/report.html", json=edit).status_code == 400


def test_delivery_owner_and_evidence_revocation(environment):
    client, _, app = environment
    item = completed(environment)
    base = f"{PREFIX}/tasks/{item['id']}"
    for suffix in (
        "/artifacts",
        "/artifacts/report.md",
        "/artifacts/report.md/download",
        "/delivery.zip",
    ):
        assert (
            client.get(
                base + suffix, headers={"Authorization": "Bearer " + BOB}
            ).status_code
            == 404
        )
    library = app.state.store.create_library("alice", "evidence")
    item.update(library_ids=[library["id"]], library_revisions={library["id"]: 0})
    app.state.store.save_task(item)
    assert client.get(base + "/artifacts").status_code == 200
    app.state.store.delete_library(library["id"])
    for suffix in ("/artifacts", "/artifacts/report.md/download", "/delivery.zip"):
        assert client.get(base + suffix).status_code == 403


def test_delivery_concurrent_edit_one_winner_and_stale_task(environment):
    _, _, app = environment
    item = completed(environment)
    delivery = Deliveries(app.state.store)
    expected = digest(delivery.files(item)["report.md"])

    def save(value):
        try:
            delivery.save(item, value, expected)
            return True
        except FileExistsError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, ["first", "second"]))
    assert sum(results) == 1
    changed = item | {"status": "ready", "report": None}
    app.state.store.save_task(changed)
    with pytest.raises(PermissionError):
        delivery.files(item)


def test_delivery_size_limit(environment):
    _, _, app = environment
    item = completed(environment)
    delivery = Deliveries(app.state.store)
    original = delivery.files(item)["report.md"]
    with pytest.raises(ValueError):
        delivery.save(item, "字" * (MAX_DELIVERY_BYTES // 3 + 1), digest(original))
    assert delivery.files(item)["report.md"] == original
