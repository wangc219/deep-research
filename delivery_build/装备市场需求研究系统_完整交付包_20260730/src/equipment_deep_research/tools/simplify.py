"""HTML-to-evidence text simplification with stable paragraph locations."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from bs4 import BeautifulSoup

from equipment_deep_research.tools.artifacts import SecureArtifactStore


@dataclass(frozen=True)
class ParagraphRef:
    index: int
    text: str
    location: str


@dataclass(frozen=True)
class SimplifiedPage:
    title: str
    published_at: str | None
    paragraphs: list[ParagraphRef]
    text: str
    raw_content_hash: str
    simplified_artifact_ref: str


def simplify_html(html: str | bytes, artifact_store: SecureArtifactStore) -> SimplifiedPage:
    raw = html.decode("utf-8", errors="replace") if isinstance(html, bytes) else html
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "aside", "noscript", "form"]):
        tag.decompose()
    root = soup.find("article") or soup.find("main") or soup.body or soup
    title = _text(soup.find("title")) or _text(soup.find("h1")) or "未命名页面"
    published_at = _published_at(soup)
    texts = [_text(tag) for tag in root.find_all(["p", "li", "h2", "h3"])]
    texts = [text for text in texts if len(text) >= 12]
    if not texts:
        body = _text(root)
        texts = [body] if body else []
    rendered = "\n\n".join(f"[{index + 1}] {text}" for index, text in enumerate(texts))
    content_hash = sha256(raw.encode("utf-8")).hexdigest()
    ref = artifact_store.put(
        rendered,
        kind="text",
        meta={"content_type": "text/plain", "materialization_status": "simplified", "content_hash": content_hash},
    )
    paragraphs = [ParagraphRef(index + 1, text, f"{ref}#p{index + 1}") for index, text in enumerate(texts)]
    return SimplifiedPage(title, published_at, paragraphs, rendered, content_hash, ref)


def paragraph_at(page: SimplifiedPage, location: str) -> ParagraphRef:
    prefix, separator, suffix = location.partition("#p")
    if prefix != page.simplified_artifact_ref or not separator or not suffix.isdigit():
        raise KeyError("invalid paragraph location")
    index = int(suffix)
    return page.paragraphs[index - 1]


def _text(tag: object) -> str:
    return " ".join(tag.get_text(" ", strip=True).split()) if tag else ""  # type: ignore[union-attr]


def _published_at(soup: BeautifulSoup) -> str | None:
    tag = soup.find("time")
    if tag:
        return str(tag.get("datetime") or _text(tag))
    meta = soup.find("meta", attrs={"property": "article:published_time"})
    return str(meta.get("content")) if meta and meta.get("content") else None
