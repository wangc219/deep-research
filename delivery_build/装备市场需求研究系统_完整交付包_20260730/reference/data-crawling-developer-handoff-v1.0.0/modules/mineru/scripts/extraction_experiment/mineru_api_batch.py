"""MinerU Precision API batch runner for local PDF files."""

from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import time
from typing import Any
import zipfile

import requests


SUPPORTED_SUFFIXES = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".png", ".jpg", ".jpeg"}
NEEDED_ZIP_SUFFIXES = {".md", ".json", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


def run_batch(
    *,
    source_root: str,
    output_root: str,
    base_url: str = "https://mineru.net",
    token_env_var: str = "MINERU_TOKEN",
    model_version: str = "vlm",
    language: str = "ch",
    enable_table: bool = True,
    enable_formula: bool = True,
    is_ocr: bool = True,
    batch_size: int = 1,
    limit: int = 1,
    force: bool = False,
    timeout_seconds: int = 1800,
    poll_interval_seconds: int = 10,
    artifact_root: str | None = None,
) -> dict[str, Any]:
    source_dir = Path(source_root).expanduser().resolve()
    output_dir = Path(output_root).expanduser().resolve()
    artifact_dir_root = (
        Path(artifact_root).expanduser().resolve()
        if artifact_root
        else output_dir.parent / "mineru_artifacts"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir_root.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "_api_batch_report.jsonl"

    token = _load_token(token_env_var)
    pdf_paths = _discover_source_files(source_dir)
    if limit and limit > 0:
        pdf_paths = pdf_paths[:limit]

    queued = 0
    saved = 0
    extract_failed = 0
    missing_result = 0
    batch_failed = 0

    for batch in _batched(pdf_paths, max(1, batch_size)):
        pending = []
        for source_path in batch:
            relative_path = source_path.relative_to(source_dir)
            markdown_path = (output_dir / relative_path).with_suffix(".md")
            artifact_dir = (artifact_dir_root / relative_path).with_suffix("")
            if markdown_path.exists() and not force:
                _append_report(
                    report_path,
                    {
                        "pdf": str(source_path),
                        "relative_data_id": relative_path.as_posix(),
                        "status": "skipped_existing",
                        "raw_md": str(markdown_path),
                        "artifact_dir": str(artifact_dir),
                    },
                )
                saved += 1
                continue
            pending.append(source_path)

        if not pending:
            continue

        try:
            batch_id = _submit_and_upload_batch(
                files=pending,
                source_dir=source_dir,
                base_url=base_url,
                token=token,
                model_version=model_version,
                language=language,
                enable_table=enable_table,
                enable_formula=enable_formula,
                is_ocr=is_ocr,
            )
            queued += len(pending)
            results = _poll_batch_results(
                batch_id=batch_id,
                base_url=base_url,
                token=token,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
            )
        except Exception as exc:
            batch_failed += len(pending)
            for source_path in pending:
                _append_report(
                    report_path,
                    {
                        "pdf": str(source_path),
                        "status": "batch_failed",
                        "error": str(exc),
                    },
                )
            continue

        results_by_key = _index_results(results)
        for source_path in pending:
            relative_path = source_path.relative_to(source_dir)
            relative_data_id = relative_path.as_posix()
            api_data_id = _api_data_id(relative_path)
            result = (
                results_by_key.get(api_data_id)
                or results_by_key.get(relative_data_id)
                or results_by_key.get(source_path.name)
            )
            if not result:
                missing_result += 1
                _append_report(
                    report_path,
                    {
                        "pdf": str(source_path),
                        "relative_data_id": relative_data_id,
                        "api_data_id": api_data_id,
                        "status": "missing_result",
                        "batch_id": batch_id,
                    },
                )
                continue

            state = result.get("state", "")
            if state != "done":
                extract_failed += 1
                _append_report(
                    report_path,
                    {
                        "pdf": str(source_path),
                        "relative_data_id": relative_data_id,
                        "api_data_id": api_data_id,
                        "status": "extract_failed",
                        "state": state,
                        "error": result.get("err_msg", ""),
                        "batch_id": batch_id,
                    },
                )
                continue

            zip_url = result.get("full_zip_url")
            if not zip_url:
                missing_result += 1
                _append_report(
                    report_path,
                    {
                        "pdf": str(source_path),
                        "relative_data_id": relative_data_id,
                        "api_data_id": api_data_id,
                        "status": "missing_zip_url",
                        "batch_id": batch_id,
                    },
                )
                continue

            markdown_path = (output_dir / relative_path).with_suffix(".md")
            artifact_dir = (artifact_dir_root / relative_path).with_suffix("")
            artifact_result = _download_mineru_result_zip(zip_url, artifact_dir)
            markdown_text = artifact_result["markdown_text"]
            markdown_path.parent.mkdir(parents=True, exist_ok=True)
            markdown_path.write_text(markdown_text, encoding="utf-8")
            saved += 1
            _append_report(
                report_path,
                {
                    "pdf": str(source_path),
                    "relative_data_id": relative_data_id,
                    "api_data_id": api_data_id,
                    "status": "saved",
                    "batch_id": batch_id,
                    "raw_md": str(markdown_path),
                    "is_ocr": is_ocr,
                    "model_version": model_version,
                    "artifact_dir": str(artifact_dir),
                    "artifact_manifest": artifact_result["manifest_path"],
                    "result_zip": artifact_result["zip_path"],
                    "markdown_zip_name": artifact_result["markdown_zip_name"],
                },
            )

    return {
        "queued": queued,
        "saved": saved,
        "extract_failed": extract_failed,
        "missing_result": missing_result,
        "batch_failed": batch_failed,
        "report_path": str(report_path),
        "output_root": str(output_dir),
        "artifact_root": str(artifact_dir_root),
    }


def _load_token(token_env_var: str) -> str:
    token = os.environ.get(token_env_var)
    if token:
        return token
    env_path = Path.cwd() / ".env"
    if env_path.exists():
        pattern = re.compile(rf"^\s*\$env:{re.escape(token_env_var)}\s*=\s*[\"'](.+?)[\"']\s*$")
        for line in env_path.read_text(encoding="utf-8").splitlines():
            match = pattern.match(line)
            if match:
                return match.group(1)
    raise RuntimeError(f"{token_env_var} is not set")


def _discover_source_files(source_dir: Path) -> list[Path]:
    if not source_dir.exists():
        raise FileNotFoundError(f"source_root not found: {source_dir}")
    return sorted(
        path
        for path in source_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    )


def _submit_and_upload_batch(
    *,
    files: list[Path],
    source_dir: Path,
    base_url: str,
    token: str,
    model_version: str,
    language: str,
    enable_table: bool,
    enable_formula: bool,
    is_ocr: bool,
) -> str:
    session = requests.Session()
    header = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    payload = {
        "files": [
            {
                "name": path.name,
                "data_id": _api_data_id(path.relative_to(source_dir)),
                "is_ocr": is_ocr,
            }
            for path in files
        ],
        "model_version": model_version,
        "language": language,
        "enable_table": enable_table,
        "enable_formula": enable_formula,
    }
    response = session.post(
        f"{base_url.rstrip('/')}/api/v4/file-urls/batch",
        headers=header,
        json=payload,
        timeout=60,
    )
    response.raise_for_status()
    result = response.json()
    if result.get("code") != 0:
        raise RuntimeError(f"MinerU upload URL request failed: {result.get('msg')}")
    batch_id = result["data"]["batch_id"]
    upload_urls = result["data"]["file_urls"]
    if len(upload_urls) != len(files):
        raise RuntimeError(
            f"MinerU returned {len(upload_urls)} upload urls for {len(files)} files"
        )

    for source_path, upload_url in zip(files, upload_urls):
        with source_path.open("rb") as file_obj:
            upload_response = session.put(upload_url, data=file_obj, timeout=300)
        if upload_response.status_code not in {200, 204}:
            raise RuntimeError(
                f"MinerU upload failed for {source_path.name}: "
                f"status={upload_response.status_code}"
            )
    return batch_id


def _poll_batch_results(
    *,
    batch_id: str,
    base_url: str,
    token: str,
    timeout_seconds: int,
    poll_interval_seconds: int,
) -> list[dict[str, Any]]:
    session = requests.Session()
    header = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    deadline = time.monotonic() + timeout_seconds
    last_results: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        response = session.get(
            f"{base_url.rstrip('/')}/api/v4/extract-results/batch/{batch_id}",
            headers=header,
            timeout=60,
        )
        response.raise_for_status()
        result = response.json()
        if result.get("code") != 0:
            raise RuntimeError(f"MinerU batch poll failed: {result.get('msg')}")
        last_results = list(result.get("data", {}).get("extract_result", []) or [])
        states = {item.get("state") for item in last_results}
        if last_results and states <= {"done", "failed"}:
            return last_results
        time.sleep(max(1, poll_interval_seconds))
    raise TimeoutError(f"MinerU batch timed out: {batch_id}; last_results={last_results}")


def _download_mineru_result_zip(
    zip_url: str,
    artifact_dir: Path,
    max_attempts: int = 3,
) -> dict[str, Any]:
    session = requests.Session()
    last_error: Exception | None = None
    for attempt in range(1, max(1, max_attempts) + 1):
        try:
            response = session.get(zip_url, timeout=300)
            response.raise_for_status()
            return extract_mineru_result_zip(response.content, artifact_dir)
        except requests.RequestException as exc:
            last_error = exc
            if attempt >= max_attempts:
                break
            time.sleep(min(30, 2 * attempt))
    if last_error is not None:
        raise last_error
    raise RuntimeError("MinerU result zip download failed without an exception")


def extract_mineru_result_zip(
    zip_bytes: bytes,
    artifact_dir: Path,
    raw_zip_name: str = "result.zip",
) -> dict[str, Any]:
    artifact_root = Path(artifact_dir).expanduser().resolve()
    artifact_root.mkdir(parents=True, exist_ok=True)
    zip_path = artifact_root / raw_zip_name
    zip_path.write_bytes(zip_bytes)

    markdown_artifacts: list[str] = []
    json_artifacts: list[str] = []
    image_artifacts: list[str] = []
    saved_artifacts: list[str] = []
    skipped_artifacts: list[str] = []

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            zip_name = info.filename.replace("\\", "/")
            if not _is_needed_zip_artifact(zip_name):
                continue
            target_path = _safe_artifact_target(artifact_root, zip_name)
            if target_path is None:
                skipped_artifacts.append(zip_name)
                continue
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(archive.read(info))
            relative_name = target_path.relative_to(artifact_root).as_posix()
            saved_artifacts.append(relative_name)
            suffix = target_path.suffix.lower()
            if suffix == ".md":
                markdown_artifacts.append(relative_name)
            elif suffix == ".json":
                json_artifacts.append(relative_name)
            elif suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}:
                image_artifacts.append(relative_name)

    markdown_zip_name = _select_markdown_artifact(markdown_artifacts)
    if not markdown_zip_name:
        raise RuntimeError("MinerU result zip does not contain markdown")
    markdown_text = (artifact_root / Path(markdown_zip_name)).read_text(encoding="utf-8")

    manifest = {
        "raw_zip": raw_zip_name,
        "markdown_zip_name": markdown_zip_name,
        "saved_artifacts": saved_artifacts,
        "markdown_artifacts": markdown_artifacts,
        "json_artifacts": json_artifacts,
        "image_artifacts": image_artifacts,
        "skipped_artifacts": skipped_artifacts,
    }
    manifest_path = artifact_root / "artifact_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        **manifest,
        "artifact_dir": str(artifact_root),
        "zip_path": str(zip_path),
        "manifest_path": str(manifest_path),
        "markdown_text": markdown_text,
    }


def _is_needed_zip_artifact(zip_name: str) -> bool:
    return PurePosixPath(zip_name).suffix.lower() in NEEDED_ZIP_SUFFIXES


def _safe_artifact_target(artifact_root: Path, zip_name: str) -> Path | None:
    posix_path = PurePosixPath(zip_name)
    if posix_path.is_absolute():
        return None
    if not posix_path.parts or any(part in {"", ".", ".."} for part in posix_path.parts):
        return None
    if ":" in posix_path.parts[0]:
        return None
    target_path = (artifact_root / Path(*posix_path.parts)).resolve()
    try:
        target_path.relative_to(artifact_root)
    except ValueError:
        return None
    return target_path


def _select_markdown_artifact(markdown_artifacts: list[str]) -> str:
    full_markdown = [
        name
        for name in markdown_artifacts
        if PurePosixPath(name).name.lower() == "full.md"
    ]
    candidates = full_markdown or markdown_artifacts
    return candidates[0] if candidates else ""


def _index_results(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for item in results:
        for key in (item.get("data_id"), item.get("file_name")):
            if key:
                indexed[str(key)] = item
    return indexed


def _api_data_id(relative_path: Path) -> str:
    digest = hashlib.sha1(relative_path.as_posix().encode("utf-8")).hexdigest()
    suffix = relative_path.suffix.lower() or ".pdf"
    return f"pdf_{digest}{suffix}"


def _batched(items: list[Path], batch_size: int):
    for index in range(0, len(items), batch_size):
        yield items[index : index + batch_size]


def _append_report(report_path: Path, record: dict[str, Any]) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("a", encoding="utf-8") as report_file:
        report_file.write(json.dumps(record, ensure_ascii=False) + "\n")
