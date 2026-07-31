from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any


TOOL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = TOOL_ROOT.parent
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "raw"


def safe_filename(value: str, *, max_length: int = 80) -> str:
    value = str(value or "").strip()
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", value)
    value = re.sub(r"\s+", "_", value)
    value = re.sub(r"_+", "_", value)
    value = value.strip("._ ")
    if not value:
        value = "untitled"
    return value[:max_length].rstrip("._ ") or "untitled"


class CollectionStorage:
    def __init__(self, base_dir: Path | str = DEFAULT_OUTPUT_DIR) -> None:
        self.base_dir = Path(base_dir)

    def write_collection(self, *, account: dict[str, Any], articles: list[dict[str, Any]]) -> dict[str, Path]:
        account_name = account.get("nickname") or account.get("name") or account.get("fakeid") or "wechat_mp"
        account_dir = self.base_dir / safe_filename(str(account_name))
        html_dir = account_dir / "html"
        markdown_dir = account_dir / "markdown"
        html_dir.mkdir(parents=True, exist_ok=True)
        markdown_dir.mkdir(parents=True, exist_ok=True)

        metadata = {
            "account": account,
            "article_count": len(articles),
            "saved_at": int(time.time()),
            "saved_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        }
        metadata_path = account_dir / "metadata.json"
        articles_json_path = account_dir / "articles.json"
        articles_jsonl_path = account_dir / "articles.jsonl"

        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        articles_json_path.write_text(json.dumps(articles, ensure_ascii=False, indent=2), encoding="utf-8")
        with articles_jsonl_path.open("w", encoding="utf-8") as file:
            for article in articles:
                file.write(json.dumps(article, ensure_ascii=False) + "\n")

        for index, article in enumerate(articles, start=1):
            stem = article_stem(article, index=index)
            html = article.get("content_html") or article.get("content") or ""
            markdown = article.get("content_markdown") or ""
            if html:
                (html_dir / f"{stem}.html").write_text(render_html(article, html), encoding="utf-8")
            if markdown:
                (markdown_dir / f"{stem}.md").write_text(render_markdown(article, markdown), encoding="utf-8")

        return {
            "account_dir": account_dir,
            "metadata": metadata_path,
            "articles_json": articles_json_path,
            "articles_jsonl": articles_jsonl_path,
            "html_dir": html_dir,
            "markdown_dir": markdown_dir,
        }


def article_stem(article: dict[str, Any], *, index: int) -> str:
    timestamp = int(article.get("update_time") or article.get("create_time") or article.get("publish_time") or 0)
    date_prefix = time.strftime("%Y%m%d", time.localtime(timestamp)) if timestamp else f"{index:03d}"
    title = safe_filename(str(article.get("title") or article.get("aid") or index), max_length=60)
    aid = safe_filename(str(article.get("aid") or article.get("id") or index), max_length=20)
    return safe_filename(f"{date_prefix}_{index:03d}_{title}_{aid}", max_length=120)


def render_html(article: dict[str, Any], content_html: str) -> str:
    title = _escape_html(str(article.get("title") or ""))
    url = _escape_html(str(article.get("url") or ""))
    return (
        "<!doctype html>\n"
        "<html lang=\"zh-CN\">\n"
        "<head><meta charset=\"utf-8\"><title>"
        + title
        + "</title></head>\n"
        "<body>\n"
        f"<h1>{title}</h1>\n"
        f"<p><a href=\"{url}\">{url}</a></p>\n"
        f"{content_html}\n"
        "</body>\n</html>\n"
    )


def render_markdown(article: dict[str, Any], markdown: str) -> str:
    title = str(article.get("title") or "")
    lines = [
        f"# {title}",
        "",
        f"- URL: {article.get('url') or ''}",
        f"- AID: {article.get('aid') or article.get('id') or ''}",
        f"- create_time: {article.get('create_time') or ''}",
        f"- update_time: {article.get('update_time') or article.get('publish_time') or ''}",
        "",
        markdown.strip(),
        "",
    ]
    return "\n".join(lines)


def _escape_html(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
