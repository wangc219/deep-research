"""Build a deterministic, secret-free developer handoff package."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import shutil
import zipfile


MODULE_MAPPINGS = {
    "journal": [
        ("scripts/journal", "scripts/journal"),
        ("tests/test_journal_download_common.py", "tests/test_journal_download_common.py"),
        ("tests/test_download_zsdd.py", "tests/test_download_zsdd.py"),
        ("tests/test_download_ktfy.py", "tests/test_download_ktfy.py"),
        ("tests/test_download_hkxb.py", "tests/test_download_hkxb.py"),
        ("tests/test_download_wanfang_journals.py", "tests/test_download_wanfang_journals.py"),
        ("tests/test_download_all_journals.py", "tests/test_download_all_journals.py"),
    ],
    "cnki": [
        ("cnki_keyword_crawler", "cnki_keyword_crawler"),
        ("tests/test_cnki_keyword_crawler_paths.py", "tests/test_cnki_keyword_crawler_paths.py"),
    ],
    "wechat": [
        ("wechat_mp_collector", "wechat_mp_collector"),
    ],
    "mineru": [
        ("scripts/extraction_experiment/__init__.py", "scripts/extraction_experiment/__init__.py"),
        ("scripts/extraction_experiment/mineru_api_batch.py", "scripts/extraction_experiment/mineru_api_batch.py"),
        ("scripts/extraction_experiment/prepare_chunks.py", "scripts/extraction_experiment/prepare_chunks.py"),
        ("scripts/extraction_experiment/models.py", "scripts/extraction_experiment/models.py"),
        ("src/knowledgegraph/__init__.py", "src/knowledgegraph/__init__.py"),
        ("src/knowledgegraph/extraction/__init__.py", "src/knowledgegraph/extraction/__init__.py"),
        ("src/knowledgegraph/extraction/models.py", "src/knowledgegraph/extraction/models.py"),
        ("src/knowledgegraph/extraction/schema.py", "src/knowledgegraph/extraction/schema.py"),
        ("tests/test_mineru_api_batch.py", "tests/test_mineru_api_batch.py"),
    ],
    "demand_discovery": [
        ("scripts/demand_discovery_autonomous_research.py", "scripts/demand_discovery_autonomous_research.py"),
        ("scripts/demand_discovery_scheduler.py", "scripts/demand_discovery_scheduler.py"),
        ("src/knowledgegraph/__init__.py", "src/knowledgegraph/__init__.py"),
        ("src/knowledgegraph/demand_discovery", "src/knowledgegraph/demand_discovery"),
        ("src/knowledgegraph/runtime", "src/knowledgegraph/runtime"),
        ("configs/demand_discovery", "configs/demand_discovery"),
        ("tests/fixtures", "tests/fixtures"),
        ("tests/test_data_crawling_provider_config.py", "tests/test_data_crawling_provider_config.py"),
        ("tests/test_demand_discovery_http_transport.py", "tests/test_demand_discovery_http_transport.py"),
        ("tests/test_demand_discovery_tool_acquisition.py", "tests/test_demand_discovery_tool_acquisition.py"),
        ("tests/test_demand_discovery_tool_fetch_page.py", "tests/test_demand_discovery_tool_fetch_page.py"),
        ("tests/test_demand_discovery_tool_search.py", "tests/test_demand_discovery_tool_search.py"),
        ("tests/test_demand_discovery_open_source_fetch.py", "tests/test_demand_discovery_open_source_fetch.py"),
        ("tests/test_demand_discovery_open_search_adapters.py", "tests/test_demand_discovery_open_search_adapters.py"),
    ],
}
MODULE_DIRECTORIES = {
    "journal": "journal",
    "cnki": "cnki",
    "wechat": "wechat",
    "mineru": "mineru",
    "demand_discovery": "demand_discovery",
}
HANDOFF_SOURCE_FILES = (
    "__init__.py",
    "commands.py",
    "doctor.py",
    "cli.py",
    "package_builder.py",
)
HANDOFF_TEST_FILES = (
    "tests/test_data_crawling_handoff_commands.py",
    "tests/test_data_crawling_handoff_package.py",
)
ROOT_TEMPLATE_FILES = (
    "README_START_HERE.md",
    "MODULE_GUIDE.md",
    "ARCHITECTURE.md",
    "SECURITY.md",
    "TROUBLESHOOTING.md",
    "LIVE_TEST_REPORT.md",
    ".env.example",
    "requirements.txt",
    "crawler.py",
    "Dockerfile",
    ".dockerignore",
    "compose.yaml",
    "bin/start-novnc.sh",
)
EXCLUDED_NAMES = {
    ".env",
    "cookie.txt",
    "session.json",
    "wx_qrcode.png",
    "__pycache__",
    ".pytest_cache",
    ".git",
    ".mypy_cache",
    ".ruff_cache",
    ".ds_store",
}
SECRET_PATTERNS = (
    ("openai_like_token", re.compile("s" + r"k-[A-Za-z0-9_-]{16,}")),
    ("tavily_token", re.compile("tv" + r"ly-[A-Za-z0-9_-]{12,}")),
    (
        "credential_assignment",
        re.compile(
            r"(?i)(api[_-]?key|authorization|cookie)\s*[:=]\s*['\"][^'\"]{8,}"
        ),
    ),
)
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


@dataclass(frozen=True)
class PackageBuildResult:
    package_root: Path
    zip_path: Path
    checksum_path: Path
    file_count: int


def build_package(
    project_root: Path,
    output_root: Path,
    version: str,
    live_report: Path | None = None,
) -> PackageBuildResult:
    project_root = Path(project_root).resolve()
    output_root = Path(output_root)
    if not output_root.is_absolute():
        output_root = project_root / output_root
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    normalized_version = _normalize_version(version)
    package_root = output_root / f"data-crawling-developer-handoff-{normalized_version}"
    _recreate_package_root(package_root, output_root)

    for module_name, mappings in MODULE_MAPPINGS.items():
        module_root = package_root / "modules" / MODULE_DIRECTORIES[module_name]
        for source_name, destination_name in mappings:
            _copy_path(project_root / source_name, module_root / destination_name)

    handoff_source = project_root / "scripts" / "data_crawling_handoff"
    _copy_path(handoff_source, package_root / "scripts" / "data_crawling_handoff")
    _copy_path(
        project_root / "scripts" / "package_data_crawling_handoff.py",
        package_root / "scripts" / "package_data_crawling_handoff.py",
    )
    for source_name in HANDOFF_TEST_FILES:
        _copy_path(project_root / source_name, package_root / source_name)

    templates_root = handoff_source / "templates"
    for relative_name in ROOT_TEMPLATE_FILES:
        _copy_path(templates_root / relative_name, package_root / relative_name)
    if live_report is not None:
        _copy_path(Path(live_report).resolve(), package_root / "LIVE_TEST_REPORT.md")

    config_source = project_root / "configs" / "demand_discovery"
    if config_source.exists():
        _copy_path(config_source, package_root / "configs" / "demand_discovery")

    for directory in (
        package_root / "data" / "raw",
        package_root / "data" / "processed",
        package_root / "runtime" / "sessions",
        package_root / "examples",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    (package_root / "VERSION").write_text(
        f"{normalized_version}\n", encoding="utf-8", newline="\n"
    )

    _scan_for_secrets(package_root)
    checksum_path = package_root / "MANIFEST.sha256"
    _write_checksums(package_root, checksum_path)

    zip_path = output_root / f"{package_root.name}.zip"
    if zip_path.exists():
        zip_path.unlink()
    _write_deterministic_zip(package_root, zip_path)
    file_count = sum(1 for path in package_root.rglob("*") if path.is_file())
    return PackageBuildResult(package_root, zip_path, checksum_path, file_count)


def _normalize_version(version: str) -> str:
    normalized = str(version).strip()
    if not re.fullmatch(r"v?[0-9]+(?:\.[0-9]+){1,3}(?:[-A-Za-z0-9.]*)?", normalized):
        raise ValueError("version must look like v1.0.0")
    return normalized if normalized.startswith("v") else f"v{normalized}"


def _recreate_package_root(package_root: Path, output_root: Path) -> None:
    resolved_package = package_root.resolve()
    resolved_output = output_root.resolve()
    if resolved_package.parent != resolved_output:
        raise ValueError("package directory must be a direct child of output_root")
    if not resolved_package.name.startswith("data-crawling-developer-handoff-v"):
        raise ValueError("refusing to replace an unexpected package directory")
    if resolved_package.exists():
        shutil.rmtree(resolved_package)
    resolved_package.mkdir(parents=True)


def _copy_path(source: Path, destination: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(f"required package source is missing: {source}")
    if source.is_symlink():
        raise ValueError(f"symbolic links are not allowed in package sources: {source}")
    if _excluded(source):
        return
    if source.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return
    destination.mkdir(parents=True, exist_ok=True)
    for child in sorted(source.iterdir(), key=lambda path: path.name.lower()):
        if not _excluded(child):
            _copy_path(child, destination / child.name)


def _excluded(path: Path) -> bool:
    return path.name.lower() in EXCLUDED_NAMES


def _scan_for_secrets(package_root: Path) -> None:
    findings: list[tuple[str, str]] = []
    for path in sorted(
        (item for item in package_root.rglob("*") if item.is_file()),
        key=lambda item: item.relative_to(package_root).as_posix(),
    ):
        relative = path.relative_to(package_root).as_posix()
        text = path.read_bytes().decode("utf-8", errors="ignore")
        for line in text.splitlines():
            if path.name == ".env.example" and _placeholder_line(line):
                continue
            if _marked_test_placeholder(relative, line):
                continue
            for label, pattern in SECRET_PATTERNS:
                if pattern.search(line):
                    findings.append((relative, label))
    if findings:
        summary = ", ".join(f"{path} ({label})" for path, label in findings)
        raise ValueError(f"secret pattern detected in package files: {summary}")


def _placeholder_line(line: str) -> bool:
    normalized = line.lower()
    return any(
        marker in normalized
        for marker in ("replace-with", "your-key", "example", "changeme", "placeholder")
    )


def _marked_test_placeholder(relative: str, line: str) -> bool:
    parts = relative.lower().split("/")
    is_test_path = "tests" in parts or parts[-1].startswith("test_")
    if not is_test_path:
        return False
    normalized = line.lower()
    return any(
        marker in normalized
        for marker in (
            "fixture",
            "test",
            "do-not-print",
            "from-env-file",
            "replace-with",
        )
    )


def _write_checksums(package_root: Path, checksum_path: Path) -> None:
    rows: list[str] = []
    files = sorted(
        (
            path
            for path in package_root.rglob("*")
            if path.is_file() and path != checksum_path
        ),
        key=lambda path: path.relative_to(package_root).as_posix(),
    )
    for path in files:
        relative = path.relative_to(package_root).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append(f"{digest}  {relative}")
    checksum_path.write_text("\n".join(rows) + "\n", encoding="utf-8", newline="\n")


def _write_deterministic_zip(package_root: Path, zip_path: Path) -> None:
    entries = sorted(
        package_root.rglob("*"),
        key=lambda path: path.relative_to(package_root).as_posix(),
    )
    with zipfile.ZipFile(
        zip_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for path in entries:
            relative = path.relative_to(package_root).as_posix()
            archive_name = f"{package_root.name}/{relative}"
            if path.is_dir():
                info = zipfile.ZipInfo(f"{archive_name}/", _ZIP_TIMESTAMP)
                info.create_system = 3
                info.external_attr = (0o755 << 16) | 0x10
                archive.writestr(info, b"")
                continue
            info = zipfile.ZipInfo(archive_name, _ZIP_TIMESTAMP)
            info.create_system = 3
            mode = 0o755 if path.suffix == ".sh" else 0o644
            info.external_attr = mode << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
