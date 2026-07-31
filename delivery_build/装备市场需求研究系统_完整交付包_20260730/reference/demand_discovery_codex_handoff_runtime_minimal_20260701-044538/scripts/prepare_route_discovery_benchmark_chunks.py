"""Prepare visible-source chunks for the route discovery benchmark.

The script reads gold cases and the source manifest, then builds a compact
DocumentChunk JSONL from visible sources only. Hidden bridge sources are never
read. Chunk selection is gold-alias guided, so the output is an extraction-stage
diagnostic input rather than a fair retrieval benchmark input.
"""

from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from typing import Any


DEFAULT_OUTPUT_DIR = Path(
    "data/processed/extraction_experiments/route_discovery_visible_v4_3_gold_guided"
)
PREPROCESS_VERSION = "route-visible-preprocess-v2"
SKIP_HTML_TAGS = {"script", "style", "noscript", "nav", "header", "footer", "aside", "form", "select", "button"}
BLOCK_HTML_TAGS = {"p", "div", "br", "section", "article", "main", "h1", "h2", "h3", "h4", "li", "tr"}
PREFERRED_HTML_TAGS = {"article", "main"}
PREFERRED_CONTAINER_KEYWORDS = {
    "abstract",
    "article",
    "body",
    "content",
    "detail",
    "fulltext",
    "main",
    "paper",
}
NAVIGATION_NOISE_TERMS = {
    "首页",
    "资讯",
    "期刊",
    "专题",
    "热点",
    "推荐论文",
    "最多阅读",
    "最多下载",
    "最多引用",
    "检索",
    "高级检索",
    "期刊介绍",
    "过刊浏览",
    "浏览排行",
    "下载排行",
    "当前目录",
    "最新录用",
    "预发表",
    "下期目录",
    "推荐文章",
}


class TextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.preferred_parts: list[str] = []
        self._skip_depth = 0
        self._preferred_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_name = tag.lower()
        if tag_name in SKIP_HTML_TAGS:
            self._skip_depth += 1
            return
        if self._preferred_depth or _is_preferred_html_container(tag_name, attrs):
            self._preferred_depth += 1
        if tag_name in BLOCK_HTML_TAGS:
            self.parts.append("\n")
            if self._preferred_depth:
                self.preferred_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag_name = tag.lower()
        if tag_name in SKIP_HTML_TAGS and self._skip_depth:
            self._skip_depth -= 1
            return
        if tag_name in BLOCK_HTML_TAGS:
            self.parts.append("\n")
            if self._preferred_depth:
                self.preferred_parts.append("\n")
        if self._preferred_depth:
            self._preferred_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = data.strip()
        if text:
            self.parts.append(text)
            if self._preferred_depth:
                self.preferred_parts.append(text)

    def text(self) -> str:
        preferred = clean_html_text("\n".join(self.preferred_parts))
        if len(preferred) >= 120:
            return preferred
        return clean_html_text("\n".join(self.parts))


def _is_preferred_html_container(tag: str, attrs: list[tuple[str, str | None]]) -> bool:
    if tag in PREFERRED_HTML_TAGS:
        return True
    for name, value in attrs:
        if name.lower() not in {"class", "id", "role"} or value is None:
            continue
        normalized = value.lower()
        if any(keyword in normalized for keyword in PREFERRED_CONTAINER_KEYWORDS):
            return True
    return False


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    compact_lines: list[str] = []
    blank = False
    for line in lines:
        if not line:
            if not blank:
                compact_lines.append("")
            blank = True
            continue
        compact_lines.append(line)
        blank = False
    return "\n".join(compact_lines).strip()


def clean_html_text(text: str) -> str:
    normalized = normalize_text(text)
    lines = [
        line
        for line in normalized.splitlines()
        if not _is_navigation_noise_line(line)
    ]
    return normalize_text("\n".join(lines))


def _is_navigation_noise_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    term_hits = sum(1 for term in NAVIGATION_NOISE_TERMS if term in stripped)
    if term_hits >= 2:
        return True
    if term_hits == 1 and len(stripped) <= 16:
        return True
    if stripped in NAVIGATION_NOISE_TERMS:
        return True
    return False


def load_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt", ".json", ".jsonl"}:
        return normalize_text(path.read_text(encoding="utf-8", errors="ignore"))
    if suffix in {".html", ".htm"}:
        parser = TextHTMLParser()
        parser.feed(path.read_text(encoding="utf-8", errors="ignore"))
        return parser.text()
    if suffix == ".pdf":
        return load_pdf_text(path)
    raise ValueError(f"Unsupported source file type: {path}")


def load_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError(
            f"{path} is a PDF and pypdf is not installed; use an HTML/Markdown source or install pypdf"
        ) from exc
    reader = PdfReader(str(path))
    pages: list[str] = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return normalize_text("\n\n".join(pages))


def choose_source_path(source: dict[str, Any], manifest: dict[str, Any]) -> Path:
    candidates = [
        manifest.get("processed_path"),
        source.get("path_or_url") if source.get("path_or_url", "").lower().endswith((".md", ".html", ".htm", ".txt")) else "",
        source.get("html_snapshot_path"),
        manifest.get("html_snapshot_path"),
        source.get("raw_path"),
        manifest.get("raw_path"),
        manifest.get("local_path"),
        source.get("path_or_url"),
    ]
    for candidate in candidates:
        if not candidate or str(candidate).startswith(("http://", "https://")):
            continue
        path = Path(candidate)
        if path.exists():
            return path
    raise FileNotFoundError(f"No local source file found for {source.get('source_id')}")


def gold_terms(case: dict[str, Any]) -> list[str]:
    terms: set[str] = set()
    for items in case.get("gold_slots", {}).values():
        for item in items:
            name = str(item.get("name", "")).strip()
            if len(name) >= 2:
                terms.add(name)
            for alias in item.get("aliases", []):
                alias_text = str(alias).strip()
                if len(alias_text) >= 2:
                    terms.add(alias_text)
    return sorted(terms, key=len, reverse=True)


def split_chunks(text: str, max_chars: int) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            if current:
                chunks.append("\n\n".join(current))
                current = []
                current_len = 0
            for start in range(0, len(paragraph), max_chars):
                chunks.append(paragraph[start : start + max_chars])
            continue
        extra_len = len(paragraph) + (2 if current else 0)
        if current and current_len + extra_len > max_chars:
            chunks.append("\n\n".join(current))
            current = [paragraph]
            current_len = len(paragraph)
        else:
            current.append(paragraph)
            current_len += extra_len
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def score_chunk(text: str, terms: list[str]) -> tuple[int, list[str]]:
    hits: list[str] = []
    score = 0
    for term in terms:
        count = text.count(term)
        if count:
            hits.append(term)
            score += count * max(2, len(term))
    return score, hits


def build_chunks(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cases = read_jsonl(Path(args.gold_routes))
    sources = read_jsonl(Path(args.source_manifest))
    manifest_by_id = {str(item["source_id"]): item for item in sources}
    rows: list[dict[str, Any]] = []
    summary_sources: list[dict[str, Any]] = []

    for case in cases:
        case_id = str(case["case_id"])
        terms = gold_terms(case)
        for source in case.get("visible_sources", []):
            source_id = str(source["source_id"])
            manifest = manifest_by_id[source_id]
            if manifest.get("split") != "visible":
                raise ValueError(f"{source_id} is not a visible source")
            path = choose_source_path(source, manifest)
            text = load_text(path)
            source_chunks = split_chunks(text, args.max_chars)
            scored = []
            for index, chunk_text in enumerate(source_chunks, start=1):
                score, hits = score_chunk(chunk_text, terms)
                scored.append((score, index, hits, chunk_text))
            selected = sorted(scored, key=lambda item: (-item[0], item[1]))[: args.top_n_per_source]
            selected = [item for item in selected if item[0] > 0] or scored[:1]
            summary_sources.append(
                {
                    "case_id": case_id,
                    "source_id": source_id,
                    "path_used": str(path),
                    "source_chunk_count": len(source_chunks),
                    "selected_count": len(selected),
                    "top_scores": [
                        {"chunk_index": index, "score": score, "hits": hits}
                        for score, index, hits, _ in selected
                    ],
                }
            )
            for score, index, hits, chunk_text in selected:
                digest = hashlib.sha1(f"{source_id}:{index}:{chunk_text}".encode("utf-8")).hexdigest()[:8]
                rows.append(
                    {
                        "document_id": source_id,
                        "chunk_id": f"{case_id}-{source_id}-chunk-{index:04d}-{digest}",
                        "text": chunk_text,
                        "source_path": str(path),
                        "page": None,
                        "section_title": str(source.get("title") or manifest.get("title") or ""),
                        "metadata": {
                            "case_id": case_id,
                            "source_id": source_id,
                            "source_role": source.get("source_role") or manifest.get("use", ""),
                            "selection": "gold_alias_guided_topn_per_visible_source",
                            "selection_score": score,
                            "selection_hits": hits,
                            "preprocess_version": PREPROCESS_VERSION,
                            "source_title": source.get("title") or manifest.get("title", ""),
                        },
                    }
                )

    summary = {
        "chunk_count": len(rows),
        "selection": "gold_alias_guided_topn_per_visible_source",
        "preprocess_version": PREPROCESS_VERSION,
        "top_n_per_source": args.top_n_per_source,
        "max_chars": args.max_chars,
        "hidden_sources_used": False,
        "sources": summary_sources,
    }
    return rows, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold-routes", default="data/benchmarks/route_discovery/gold_routes_v0.jsonl")
    parser.add_argument("--source-manifest", default="data/benchmarks/route_discovery/source_manifest_v0.jsonl")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--top-n-per-source", type=int, default=4)
    parser.add_argument("--max-chars", type=int, default=5000)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    rows, summary = build_chunks(args)
    write_jsonl(output_dir / "chunks_visible_gold_guided.jsonl", rows)
    (output_dir / "chunk_selection_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
