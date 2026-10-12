"""Local-only HTTP boundary for an isolated document parsing research workflow."""

import asyncio
import copy
import fcntl
import os
import secrets
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import load_config, validate_data_dir
from .contracts import ResearchError
from .deliveries import MEDIA, NAMES, Deliveries, digest
from .parsing import MAX_UPLOAD, parse_upload
from .providers import ProviderError
from .settings import public_settings, require_admin, save_settings
from .storage import Store

PREFIX = "/document-research-api"
CONTEXT_QUESTIONS = 3
CONTEXT_QUESTION_LENGTH = 2000
QUESTIONS = {
    "parser_version": "当前使用的解析器名称、版本和关键配置是什么？",
    "expected_result": "失败样本对应的正确表格结果应是什么？",
    "constraints": "部署环境、算力、耗时和许可方面有哪些约束？",
}


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class LibraryInput(Input):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("资料库名称不能为空。")
        return value.strip()


class RetrievalInput(Input):
    problem: str = Field(min_length=1, max_length=20_000)
    library_ids: list[str] = Field(default_factory=list, max_length=20)
    allow_public: bool = False
    public_query: str = Field(default="", max_length=500)
    allow_web_search: bool = False
    parent_task_id: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("parent_task_id")
    @classmethod
    def parent_nonblank(cls, value):
        if value is not None and not value.strip():
            raise ValueError("上一轮任务标识不能为空。")
        return value

    @field_validator("problem")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("研发问题不能为空。")
        return value.strip()

    @field_validator("library_ids")
    @classmethod
    def valid_ids(cls, values):
        if len(set(values)) != len(values) or any(
            not 1 <= len(value) <= 200 for value in values
        ):
            raise ValueError("资料库选择无效或重复。")
        return values

    @model_validator(mode="after")
    def public_query_required(self):
        if self.allow_web_search and not 1 <= len(self.public_query.strip()) <= 70:
            raise ValueError("联网搜索须单独填写 1–70 字符的公开关键词。")
        return self


class TaskInput(RetrievalInput):
    mode: Literal["research", "answer"] = "research"
    parser_version: str = Field(default="", max_length=2000)
    expected_result: str = Field(default="", max_length=10_000)
    constraints: str = Field(default="", max_length=10_000)
    allow_external_model: bool = False


class TaskPatch(Input):
    parser_version: str | None = Field(default=None, max_length=2000)
    expected_result: str | None = Field(default=None, max_length=10_000)
    constraints: str | None = Field(default=None, max_length=10_000)
    accept_assumptions: bool | None = None


class WebSearchSettingsInput(Input):
    """独立公网检索的提供商、地址和引擎设置。"""

    provider: Literal["open-websearch", "zhipu"] = "open-websearch"
    base_url: str = Field(max_length=2000)
    engines: list[Literal["bing", "duckduckgo", "startpage", "sogou", "baidu"]] = Field(
        min_length=1, max_length=5
    )


class ModelSettingsInput(Input):
    base_url: str = Field(max_length=2000)
    model: str = Field(min_length=1, max_length=200)
    api_key: str = Field(default="", max_length=4096)
    clear_api_key: bool = False
    reasoning_effort: Literal["", "low", "high", "max"] = ""
    web_search: WebSearchSettingsInput | None = None

    @field_validator("api_key")
    @classmethod
    def valid_key(cls, value):
        value = value.strip()
        if any(ord(character) < 33 or ord(character) > 126 for character in value):
            raise ValueError("API 密钥不能包含空白或控制字符。")
        return value

    @model_validator(mode="after")
    def key_action(self):
        if self.api_key and self.clear_api_key:
            raise ValueError("不能同时设置和清空密钥。")
        return self


class DeliveryPatch(Input):
    content: str = Field(max_length=4 * 1024 * 1024)
    expected_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


@dataclass(frozen=True)
class Identity:
    owner: str
    token: str


class UploadLimit:
    """Bound complete incoming bodies, including chunked multipart uploads."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        total = 0

        async def bounded_receive():
            nonlocal total
            message = await receive()
            total += len(message.get("body", b""))
            if total > MAX_UPLOAD + 64 * 1024:
                raise HTTPException(413, "请求超过 10 MiB 文件限额。")
            return message

        return await self.app(scope, bounded_receive, send)


def create_app(data_dir: str | Path, engine=None) -> FastAPI:
    """组装独立本地服务；生产和测试均须显式提供专用数据目录。"""
    directory = validate_data_dir(data_dir)
    load_config(
        directory
    )  # Fail visibly at startup; never use implicit or platform credentials.
    store = Store(directory)
    deliveries = Deliveries(store)
    if engine is None:
        from .engine import Engine

        engine = Engine(lambda: load_config(directory))
    jobs: dict[str, asyncio.Task] = {}
    parser_slots = asyncio.Semaphore(2)
    retrieval_slots = asyncio.Semaphore(4)

    @asynccontextmanager
    async def lifespan(app):
        fd = os.open(
            directory / "service.lock", os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600
        )
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError(
                    "此独立数据目录已有服务运行，请勿启动第二个进程。"
                ) from exc
            store.fail_interrupted()
            try:
                yield
            finally:
                app.state.stopping = True
                for job in list(jobs.values()):
                    job.cancel()
                if jobs:
                    await asyncio.gather(*list(jobs.values()), return_exceptions=True)
        finally:
            os.close(fd)

    app = FastAPI(
        title="通用文档解析研发", lifespan=lifespan, docs_url=None, redoc_url=None
    )
    app.add_middleware(UploadLimit)
    app.state.store = store
    app.state.engine = engine
    app.state.stopping = False

    @app.middleware("http")
    async def private_responses(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(PermissionError)
    async def permission_error(_request, _exc):
        return JSONResponse(
            status_code=403, content={"detail": "访问权限已撤销，或所选资料已经变更。"}
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request, _exc):
        return JSONResponse(
            status_code=422, content={"detail": "请求字段、类型或长度不符合要求。"}
        )

    def authenticate(request: Request) -> Identity:
        authorization = request.headers.get("authorization", "")
        if (
            not authorization.startswith("Bearer ")
            or not 24 <= len(authorization[7:]) <= 512
        ):
            raise HTTPException(401, "请提供此入口专用的访问令牌。")
        token = authorization[7:]
        try:
            config = load_config(directory)
        except ValueError:
            raise HTTPException(
                503, "独立配置不可用，请检查 config.json 和文件权限。"
            ) from None
        matched_owner = None
        for owner, configured in config["tokens"].items():
            if secrets.compare_digest(token.encode(), configured.encode()):
                matched_owner = owner
        if matched_owner is None:
            raise HTTPException(401, "访问令牌无效或已撤销。")
        return Identity(matched_owner, token)

    Auth = Annotated[Identity, Depends(authenticate)]

    def current_config(identity: Identity) -> dict:
        try:
            config = load_config(directory)
        except ValueError:
            raise PermissionError("configuration unavailable") from None
        configured = config["tokens"].get(identity.owner, "")
        if not secrets.compare_digest(identity.token.encode(), configured.encode()):
            raise PermissionError("token revoked")
        return config

    def remote_libraries(config: dict, owner: str) -> list[dict]:
        zhipu = config.get("zhipu", {})
        if not isinstance(zhipu, dict):
            return []
        grants = zhipu.get("libraries", {})
        if not isinstance(grants, dict):
            return []
        libraries = grants.get(owner, [])
        if not isinstance(libraries, list):
            return []
        return [
            {
                "id": "zhipu:" + item["id"],
                "name": item.get("name", item["id"]),
                "kind": "zhipu",
                "document_count": None,
            }
            for item in libraries
            if isinstance(item, dict)
            and isinstance(item.get("id"), str)
            and 0 < len(item["id"]) <= 190
            and isinstance(item.get("name", ""), str)
        ]

    def authorize_library(identity: Identity, library_id: str) -> dict:
        config = current_config(identity)
        if library_id.startswith("local:"):
            library = store.library(library_id)
            if library and library["owner"] == identity.owner:
                return library
        else:
            for library in remote_libraries(config, identity.owner):
                if library["id"] == library_id:
                    return library
        raise PermissionError("library unavailable")

    def local_library(identity: Identity, library_id: str) -> dict:
        library = authorize_library(identity, library_id)
        if not library_id.startswith("local:"):
            raise HTTPException(400, "智谱资料库仅用于只读检索，不能在本入口管理文档。")
        return library

    def authorize_task_scope(identity: Identity, task: dict, check_revision=True):
        current_config(identity)
        if task["owner"] != identity.owner:
            raise HTTPException(404, "任务不存在。")
        for library_id in task["library_ids"]:
            library = authorize_library(identity, library_id)
            previous = task.get("library_revisions", {}).get(library_id)
            if (
                check_revision
                and previous is not None
                and library.get("revision") != previous
            ):
                raise PermissionError("library evidence changed")

    def authorize_task(identity: Identity, task: dict, check_revision=True):
        authorize_task_scope(identity, task, check_revision)
        # Keep authorization work bounded to the questions actually retained. Old
        # answers and evidence are never inherited, including from these tasks.
        for context_id in task.get("context_task_ids", []):
            context = store.task(context_id)
            if (
                context is None
                or context["owner"] != identity.owner
                or context["status"] != "completed"
                or set(context["library_ids"]) != set(task["library_ids"])
            ):
                raise PermissionError("follow-up context unavailable")
            # This check is required even when rerunning/editing the child with
            # check_revision=False: a stale parent must not silently be reused.
            authorize_task_scope(identity, context)

    def get_task(identity: Identity, task_id: str, check_revision=True) -> dict:
        task = store.task(task_id)
        if task is None:
            raise HTTPException(404, "任务不存在。")
        authorize_task(identity, task, check_revision)
        return task

    def task_response(task: dict) -> dict:
        return {
            key: value
            for key, value in task.items()
            if key not in ("owner", "library_revisions", "context_task_ids")
        }

    def followup_context(identity: Identity, task: dict) -> dict:
        parent_id = task.get("parent_task_id")
        if parent_id is None:
            return {
                "context_questions": [],
                "context_task_ids": [],
                "context_truncated": False,
            }
        parent = get_task(identity, parent_id)
        if parent["status"] != "completed":
            raise HTTPException(409, "上一轮任务尚未完成，请完成后再继续追问。")
        if set(parent["library_ids"]) != set(task["library_ids"]):
            raise HTTPException(
                409, "继续追问须保留上一轮的资料库选择；更换资料库请新建对话。"
            )
        questions = parent.get("context_questions", []) + [parent["problem"]]
        context_ids = parent.get("context_task_ids", []) + [parent_id]
        return {
            "context_questions": [
                question[:CONTEXT_QUESTION_LENGTH]
                for question in questions[-CONTEXT_QUESTIONS:]
            ],
            "context_task_ids": context_ids[-CONTEXT_QUESTIONS:],
            "context_truncated": bool(
                parent.get("context_truncated")
                or len(questions) > CONTEXT_QUESTIONS
                or any(
                    len(question) > CONTEXT_QUESTION_LENGTH for question in questions
                )
            ),
        }

    def refresh_questions(task: dict):
        if task.get("mode") == "answer":
            task.update(questions=[], assumptions=[], status="ready")
            return
        missing = [field for field in QUESTIONS if not task.get(field, "").strip()]
        task["questions"] = [
            {"field": field, "question": QUESTIONS[field]} for field in missing
        ]
        task["assumptions"] = [
            f"{QUESTIONS[field]} 未提供；相关方案假设需通过实验验证。"
            for field in missing
        ]
        task["status"] = (
            "ready" if not missing or task.get("accept_assumptions") else "needs_input"
        )

    @app.get(PREFIX + "/health")
    def health():
        try:
            configured = bool(engine.is_configured())
        except (ValueError, TypeError, OSError):
            configured = False
        return {"status": "ok", "model_configured": configured}

    @app.get(PREFIX + "/session")
    def session(identity: Auth):
        return {"user": identity.owner}

    @app.get(PREFIX + "/settings/model")
    def model_settings(identity: Auth):
        config = current_config(identity)
        require_admin(config, identity.owner, identity.token)
        return public_settings(config)

    @app.put(PREFIX + "/settings/model")
    def update_model_settings(body: ModelSettingsInput, identity: Auth):
        try:
            return save_settings(
                directory, identity.owner, identity.token, body.model_dump()
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    def delivery_task(identity, task_id):
        task = get_task(identity, task_id)
        if task["status"] != "completed" or not task.get("report"):
            raise HTTPException(409, "任务完成后才可交付文件。")
        return task

    @app.get(PREFIX + "/tasks/{task_id}/artifacts")
    def artifacts(task_id: str, identity: Auth):
        task = delivery_task(identity, task_id)
        try:
            files = deliveries.files(task)
        except ValueError as exc:
            raise HTTPException(413, str(exc)) from None
        authorize_task(identity, task)
        return {
            "items": [
                {
                    "name": name,
                    "size": len(files[name].encode()),
                    "media_type": media,
                    "editable": name == "report.md",
                }
                for name, media in zip(NAMES, MEDIA, strict=True)
            ]
        }

    @app.get(PREFIX + "/tasks/{task_id}/delivery.zip")
    def delivery_zip(task_id: str, identity: Auth):
        task = delivery_task(identity, task_id)
        content = deliveries.bundle(task)
        authorize_task(identity, task)
        return Response(
            content,
            media_type="application/zip",
            headers={
                "Content-Disposition": 'attachment; filename="document-research.zip"',
                "Cache-Control": "no-store",
            },
        )

    def delivery_file(identity, task_id, name):
        if name not in NAMES:
            raise HTTPException(404, "交付文件不存在。")
        task = delivery_task(identity, task_id)
        content = deliveries.files(task)[name]
        authorize_task(identity, task)
        return task, content

    @app.get(PREFIX + "/tasks/{task_id}/artifacts/{name}")
    def artifact(task_id: str, name: str, identity: Auth):
        _, content = delivery_file(identity, task_id, name)
        return {"name": name, "content": content, "sha256": digest(content)}

    @app.get(PREFIX + "/tasks/{task_id}/artifacts/{name}/download")
    def artifact_download(task_id: str, name: str, identity: Auth):
        _, content = delivery_file(identity, task_id, name)
        return Response(
            content.encode(),
            media_type=MEDIA[NAMES.index(name)],
            headers={
                "Content-Disposition": f'attachment; filename="{name}"',
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.put(PREFIX + "/tasks/{task_id}/artifacts/{name}")
    def edit_artifact(task_id: str, name: str, body: DeliveryPatch, identity: Auth):
        if name != "report.md":
            raise HTTPException(400, "仅 Markdown 交付副本可以编辑。")
        task = delivery_task(identity, task_id)
        try:
            result = deliveries.save(task, body.content, body.expected_sha256)
            authorize_task(identity, task)
            return result
        except FileExistsError as exc:
            raise HTTPException(409, str(exc)) from None
        except ValueError as exc:
            raise HTTPException(413, str(exc)) from None

    @app.get(PREFIX + "/libraries")
    def libraries(identity: Auth):
        return {
            "items": store.libraries(identity.owner)
            + remote_libraries(current_config(identity), identity.owner)
        }

    @app.post(PREFIX + "/libraries", status_code=201)
    def create_library(body: LibraryInput, identity: Auth):
        current_config(identity)
        return store.create_library(identity.owner, body.name)

    @app.delete(PREFIX + "/libraries/{library_id}")
    def delete_library(library_id: str, identity: Auth):
        local_library(identity, library_id)
        store.delete_library(library_id)
        return {"deleted": True}

    @app.get(PREFIX + "/libraries/{library_id}/documents")
    def documents(library_id: str, identity: Auth):
        local_library(identity, library_id)
        return {
            "items": [
                {key: value for key, value in item.items() if key != "chunks"}
                for item in store.documents(library_id)
            ]
        }

    @app.post(PREFIX + "/libraries/{library_id}/documents", status_code=201)
    async def upload(library_id: str, request: Request, identity: Auth):
        local_library(identity, library_id)
        async with request.form(
            max_files=1, max_fields=0, max_part_size=MAX_UPLOAD
        ) as form:
            file = form.get("file")
            if file is None or not hasattr(file, "read") or len(form) != 1:
                raise HTTPException(400, "请上传一个 file 字段。")
            # Store no user-controlled path or original binary on disk.
            name = (
                (file.filename or "document")
                .replace("\\", "/")
                .rsplit("/", 1)[-1][:240]
            )
            content = await file.read(MAX_UPLOAD + 1)
            if len(content) > MAX_UPLOAD:
                raise HTTPException(413, "文件超过 10 MiB 限额。")
        try:
            if parser_slots.locked():
                raise HTTPException(429, "本地服务同时最多解析 2 个文档，请稍后重试。")
            async with parser_slots:
                chunks = await parse_upload(name, content)
            error = None
        except ValueError as exc:
            chunks, error = [], str(exc)
        local_library(
            identity, library_id
        )  # Recheck permission after the slow parser operation.
        return store.create_document(library_id, name, chunks, error)

    def get_document(identity: Identity, document_id: str) -> dict:
        item = store.document(document_id)
        if not item:
            raise HTTPException(404, "文档不存在。")
        local_library(identity, item["library_id"])
        return item

    @app.get(PREFIX + "/documents/{document_id}")
    def document(document_id: str, identity: Auth):
        return get_document(identity, document_id)

    @app.delete(PREFIX + "/documents/{document_id}")
    def delete_document(document_id: str, identity: Auth):
        get_document(identity, document_id)
        store.delete_document(document_id)
        return {"deleted": True}

    def collect_sources(identity: Identity, task: dict):
        revisions = {}
        sources = []
        for library_id in task["library_ids"]:
            library = authorize_library(identity, library_id)
            if library_id.startswith("local:"):
                revisions[library_id] = library["revision"]
                for item in store.documents(library_id):
                    if item["status"] != "ready":
                        continue
                    for chunk in item["chunks"]:
                        sources.append(
                            {
                                "id": item["id"] + ":" + chunk["id"],
                                "library_id": library_id,
                                "document_id": item["id"],
                                "title": item["name"],
                                "text": chunk["text"],
                                "page": chunk["page"],
                                "source_url": None,
                                "origin": "local",
                            }
                        )
                        if len(sources) > 2000:
                            raise HTTPException(
                                413,
                                "所选资料超过单次研究范围，请减少所选资料库或拆分文档。",
                            )
        return sources, revisions

    @app.post(PREFIX + "/retrieve")
    async def retrieve(body: RetrievalInput, identity: Auth, request: Request):
        task = body.model_dump() | {"owner": identity.owner}
        task.update(followup_context(identity, task))
        sources, revisions = collect_sources(identity, task)
        task["library_revisions"] = revisions

        def authorize():
            authorize_task(identity, task)

        if retrieval_slots.locked():
            raise HTTPException(429, "同时最多检索 4 个请求，请稍后重试。")
        async with retrieval_slots:
            job = asyncio.create_task(engine.retrieve(task, sources, authorize))
            try:
                async with asyncio.timeout(145):
                    while not job.done():
                        await asyncio.wait({job}, timeout=0.2)
                        if await request.is_disconnected():
                            raise HTTPException(499, "检索请求已断开。")
                    result = await job
                    authorize()
                    return result | {
                        "context_questions": task["context_questions"],
                        "context_truncated": task["context_truncated"],
                    }
            except TimeoutError:
                raise HTTPException(504, "检索超时，请缩小范围或稍后重试。") from None
            except (ResearchError, ProviderError) as exc:
                raise HTTPException(502, str(exc)) from None
            except (PermissionError, HTTPException):
                raise
            except Exception:  # noqa: BLE001 -- Never expose private provider request/response text.
                raise HTTPException(
                    502, "检索失败，请检查独立检索配置后重试。"
                ) from None
            finally:
                if not job.done():
                    job.cancel()
                await asyncio.gather(job, return_exceptions=True)

    @app.post(PREFIX + "/tasks", status_code=201)
    def create_task(body: TaskInput, identity: Auth):
        for library_id in body.library_ids:
            authorize_library(identity, library_id)
        task = body.model_dump() | {
            "id": uuid.uuid4().hex,
            "owner": identity.owner,
            "questions": [],
            "assumptions": [],
            "error": None,
            "report": None,
            "accept_assumptions": False,
        }
        task.update(followup_context(identity, task))
        refresh_questions(task)
        store.save_task(task)
        return task_response(task)

    @app.get(PREFIX + "/tasks/{task_id}")
    def task(task_id: str, identity: Auth):
        return task_response(get_task(identity, task_id))

    @app.patch(PREFIX + "/tasks/{task_id}")
    def patch_task(task_id: str, body: TaskPatch, identity: Auth):
        task = get_task(identity, task_id, check_revision=False)
        previous = copy.deepcopy(task)
        if task["status"] == "running":
            raise HTTPException(409, "任务运行中，请先取消再编辑。")
        for key, value in body.model_dump(exclude_none=True).items():
            task[key] = value
        task.pop("library_revisions", None)
        task.update(report=None, error=None)
        refresh_questions(task)
        if not store.replace_task(previous, task):
            raise HTTPException(409, "任务在编辑期间发生变化，请刷新后重试。")
        return task_response(task)

    async def execute(task: dict, identity: Identity, local_sources: list[dict]):
        def authorize():
            authorize_task(identity, task)
            persisted = store.task(task["id"])
            if persisted is None or persisted["status"] != "running":
                raise PermissionError("task no longer running")

        try:
            authorize()
            report = await engine.run(dict(task), local_sources, authorize)
            authorize()
            report["assumptions"] = list(
                dict.fromkeys(task["assumptions"] + report.get("assumptions", []))
            )
            task.update(status="completed", report=report, error=None)
            store.finish_running(task, task["library_revisions"])
        except asyncio.CancelledError:
            persisted = store.task(task["id"])
            if persisted and persisted["status"] == "running":
                persisted.update(
                    status="failed" if app.state.stopping else "cancelled",
                    report=None,
                    error="服务停止，任务中断；请重新运行。"
                    if app.state.stopping
                    else None,
                )
                store.finish_running(persisted)
        except PermissionError:
            task.update(
                status="failed",
                report=None,
                error="任务权限已撤销，或所选资料在生成期间发生变化；结果已丢弃。",
            )
            store.finish_running(task)
        except (ResearchError, ProviderError) as exc:
            task.update(status="failed", report=None, error=str(exc))
            store.finish_running(task)
        except Exception:  # noqa: BLE001 -- Persist terminal failure without exposing provider response bodies or secrets.
            # Provider exception bodies may contain credentials or private requests.
            task.update(
                status="failed",
                report=None,
                error="研究生成失败。请检查独立模型/检索配置和来源可用性后重试。",
            )
            store.finish_running(task)
        finally:
            jobs.pop(task["id"], None)

    @app.post(PREFIX + "/tasks/{task_id}/run", status_code=202)
    async def run_task(task_id: str, identity: Auth):
        task = get_task(identity, task_id, check_revision=False)
        previous = copy.deepcopy(task)
        if task["status"] == "running" or task_id in jobs:
            raise HTTPException(409, "任务已经运行。")
        if len(jobs) >= 4:
            raise HTTPException(503, "本地服务同时最多运行 4 个研究任务，请稍后重试。")
        if task["status"] == "needs_input":
            raise HTTPException(409, "请补充关键信息，或明确接受待验证假设。")
        if not task["allow_external_model"]:
            raise HTTPException(
                400, "运行前须同意将本次问题和所选证据发送给配置的模型服务。"
            )
        try:
            configured = engine.is_configured()
        except (ValueError, TypeError, OSError):
            configured = False
        if not configured:
            raise HTTPException(
                503,
                "尚未配置可用模型。请在独立 config.json 中设置 model.base_url、api_key 和 model。",
            )
        sources, revisions = collect_sources(identity, task)
        task.update(
            status="running", report=None, error=None, library_revisions=revisions
        )
        if not store.replace_task(previous, task):
            raise HTTPException(409, "任务在启动期间发生变化，请刷新后重试。")
        jobs[task_id] = asyncio.create_task(execute(task, identity, sources))
        return task_response(task)

    @app.post(PREFIX + "/tasks/{task_id}/cancel")
    async def cancel_task(task_id: str, identity: Auth):
        # Stopping an owned in-flight request must remain possible after its
        # evidence or parent becomes unavailable. This does not grant permission
        # to read its old question, context, selected libraries or report.
        current_config(identity)
        task = store.task(task_id)
        if task is None or task["owner"] != identity.owner:
            raise HTTPException(404, "任务不存在。")
        readable = True
        try:
            authorize_task(identity, task)
        except PermissionError:
            # Do not confuse a revoked login with a revoked evidence scope.
            current_config(identity)
            if task["status"] != "running":
                raise
            readable = False
        if task["status"] == "running":
            previous = copy.deepcopy(task)
            task.update(status="cancelled", report=None, error=None)
            if not store.replace_task(previous, task):
                return task_response(get_task(identity, task_id))
            if job := jobs.get(task_id):
                job.cancel()
        if not readable:
            return {
                "id": task_id,
                "status": "cancelled",
                "mode": task.get("mode", "research"),
                "library_ids": [],
                "problem": "资料权限或内容已变更，已取消本地等待与结果输出。",
                "questions": [],
                "assumptions": [],
                "context_questions": [],
                "report": None,
                "scope_invalidated": True,
            }
        return task_response(task)

    return app
