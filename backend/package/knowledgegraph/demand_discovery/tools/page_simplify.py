"""HTML-to-structured-text simplifier for demand discovery evidence review."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from bs4 import BeautifulSoup
from bs4.element import Tag

from knowledgegraph.demand_discovery.tools.artifacts import ArtifactStore


@dataclass(frozen=True)
class Paragraph:
    index: int
    text: str


@dataclass(frozen=True)
class SimplifiedPage:
    title: str
    headings: list[str]
    lead: str
    paragraphs: list[Paragraph]
    publish_time: str | None
    author_or_org: str | None
    text_ref: str
    degraded: bool = False


NOISE_TAGS = {"script", "style", "noscript", "nav", "footer", "aside"}
DATE_RE = re.compile(r"(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?)")


def simplify(html: str, artifacts: ArtifactStore) -> SimplifiedPage:
    """Return a compact, paragraph-addressable page view."""

    try:
        soup = BeautifulSoup(html or "", "html.parser")
        _strip_noise(soup)
        root = _best_root(soup)
        title = _title(soup, root)
        headings = _headings(root)
        paragraphs = _paragraphs(root)
        degraded = False
        if not paragraphs:
            text = _clean_text(root.get_text(" ", strip=True))
            paragraphs = [text] if text else []
            degraded = True
        if not paragraphs:
            paragraphs = [_clean_text(soup.get_text(" ", strip=True))]
            degraded = True
        paragraph_objs = [
            Paragraph(index=index, text=text)
            for index, text in enumerate(paragraphs)
            if text
        ]
        normalized = "\n\n".join(item.text for item in paragraph_objs)
        text_ref = artifacts.put(
            normalized,
            kind="text",
            meta={
                "title": title,
                "paragraph_count": len(paragraph_objs),
                "content_type": "text/plain",
            },
        )
        lead = paragraph_objs[0].text if paragraph_objs else ""
        return SimplifiedPage(
            title=title,
            headings=headings,
            lead=lead,
            paragraphs=paragraph_objs,
            publish_time=_publish_time(soup),
            author_or_org=_author_or_org(soup),
            text_ref=text_ref,
            degraded=degraded,
        )
    except Exception:
        text = _clean_text(BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True))
        text_ref = artifacts.put(
            text,
            kind="text",
            meta={"paragraph_count": 1, "content_type": "text/plain", "degraded": True},
        )
        return SimplifiedPage(
            title="",
            headings=[],
            lead=text,
            paragraphs=[Paragraph(index=0, text=text)] if text else [],
            publish_time=None,
            author_or_org=None,
            text_ref=text_ref,
            degraded=True,
        )


def paragraph_at_location(artifacts: ArtifactStore, source_location: str) -> str:
    ref, index = _parse_location(source_location)
    paragraphs = _split_paragraphs(artifacts.get_text(ref))
    return paragraphs[index]


def _strip_noise(soup: BeautifulSoup) -> None:
    for tag in soup.find_all(NOISE_TAGS):
        tag.decompose()
    for tag in soup.find_all(True):
        if not isinstance(tag, Tag):
            continue
        style = str(tag.get("style", "")).replace(" ", "").lower()
        classes = {str(item).lower() for item in tag.get("class", [])}
        if "display:none" in style or "visibility:hidden" in style:
            tag.decompose()
        elif "hidden" in classes:
            tag.decompose()


def _best_root(soup: BeautifulSoup) -> Tag:
    candidates = [
        tag
        for tag in soup.find_all(["article", "main", "section", "div", "body"])
        if isinstance(tag, Tag)
    ]
    if not candidates:
        return soup
    return max(candidates, key=lambda tag: len(_clean_text(tag.get_text(" ", strip=True))))


def _title(soup: BeautifulSoup, root: Tag) -> str:
    for source in (
        root.find("h1"),
        soup.find("meta", attrs={"property": "og:title"}),
        soup.find("title"),
    ):
        if source is None:
            continue
        if isinstance(source, Tag) and source.name == "meta":
            text = str(source.get("content", ""))
        else:
            text = source.get_text(" ", strip=True) if isinstance(source, Tag) else ""
        text = _clean_text(text)
        if text:
            return text
    return ""


def _headings(root: Tag) -> list[str]:
    rows: list[str] = []
    for tag in root.find_all(["h1", "h2", "h3", "h4"]):
        text = _clean_text(tag.get_text(" ", strip=True))
        if text:
            rows.append(f"{tag.name.upper()}> {text}")
    return rows


def _paragraphs(root: Tag) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()
    for tag in root.find_all(["p", "li"]):
        text = _clean_text(tag.get_text(" ", strip=True))
        if len(text) < 8:
            continue
        if text in seen:
            continue
        seen.add(text)
        rows.append(text)
    return rows


def _publish_time(soup: BeautifulSoup) -> str | None:
    for attrs in (
        {"property": "article:published_time"},
        {"name": "publishdate"},
        {"name": "date"},
        {"name": "pubdate"},
    ):
        tag = soup.find("meta", attrs=attrs)
        if isinstance(tag, Tag):
            value = _clean_text(str(tag.get("content", "")))
            if value:
                return value
    time_tag = soup.find("time")
    if isinstance(time_tag, Tag):
        value = _clean_text(str(time_tag.get("datetime", ""))) or _clean_text(
            time_tag.get_text(" ", strip=True)
        )
        if value:
            return value
    match = DATE_RE.search(soup.get_text(" ", strip=True))
    return match.group(1) if match else None


def _author_or_org(soup: BeautifulSoup) -> str | None:
    for attrs in ({"name": "author"}, {"property": "article:author"}):
        tag = soup.find("meta", attrs=attrs)
        if isinstance(tag, Tag):
            value = _clean_text(str(tag.get("content", "")))
            if value:
                return value
    for selector in (".author", ".rich_media_meta_text", "[rel=author]"):
        tag = soup.select_one(selector)
        if isinstance(tag, Tag):
            value = _clean_text(tag.get_text(" ", strip=True))
            if value:
                return value
    return None


def _clean_text(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _split_paragraphs(text: str) -> list[str]:
    return [item.strip() for item in re.split(r"\n\s*\n", text) if item.strip()]


def _parse_location(source_location: str) -> tuple[str, int]:
    if "#para:" not in source_location:
        raise ValueError("source_location must use '<artifact_ref>#para:<index>'")
    ref, raw_index = source_location.rsplit("#para:", 1)
    return ref, int(raw_index)
