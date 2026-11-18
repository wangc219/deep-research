from __future__ import annotations

from typing import Any

from platform_core.knowledge.chunking.block_metadata import MarkdownBlockMetadataIndex
from platform_core.knowledge.chunking.ragflow_like.parsers import book, general, laws, qa, semantic, separator
from platform_core.knowledge.chunking.ragflow_like.presets import map_to_internal_parser_id, normalize_chunk_preset_id
from platform_core.knowledge.chunking.source_locator import SourceTextLocator


def _build_chunk_records(
    text_chunks: list[str],
    file_id: str,
    filename: str,
    source_text: str | None = None,
    processing_params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    search_from = 0
    source = source_text or ""
    metadata_index = MarkdownBlockMetadataIndex(source)
    source_locator = SourceTextLocator(source)
    params = dict(processing_params or {})

    for idx, chunk_content in enumerate(text_chunks):
        text = (chunk_content or "").strip()
        if not text:
            continue

        located = source_locator.locate(text, search_from=search_from)
        start_char_pos = located.start_char if located else None
        end_char_pos = located.end_char if located else None
        record_content = located.content if located else text
        if located:
            search_from = located.end_char

        metadata = metadata_index.metadata_for(
            chunk_text=record_content,
            start_char=start_char_pos,
            filename=filename,
            processing_params=params,
        )
        if located and located.match_kind != "exact":
            metadata["source_metadata"]["source_text_match"] = located.match_kind

        records.append(
            {
                "id": f"{file_id}_chunk_{idx}",
                "content": record_content,
                "file_id": file_id,
                "filename": filename,
                "chunk_index": idx,
                "source": filename,
                "chunk_id": f"{file_id}_chunk_{idx}",
                "start_char_pos": start_char_pos,
                "end_char_pos": end_char_pos,
                "start_token_pos": None,
                "end_token_pos": None,
                "extraction_result": None,
                **metadata,
            }
        )

    return records


def _dispatch_markdown_parser(
    preset_id: str, filename: str, markdown_content: str, parser_config: dict[str, Any]
) -> list[str]:
    parser_id = map_to_internal_parser_id(preset_id)

    if parser_id == "naive":
        return general.chunk_markdown(markdown_content, parser_config)
    if parser_id == "qa":
        return qa.chunk_markdown(filename, markdown_content, parser_config)
    if parser_id == "book":
        return book.chunk_markdown(markdown_content, parser_config)
    if parser_id == "laws":
        return laws.chunk_markdown(filename, markdown_content, parser_config)
    if parser_id == "semantic":
        return semantic.chunk_markdown(markdown_content, parser_config)
    if parser_id == "separator":
        return separator.chunk_markdown(markdown_content, parser_config)

    return general.chunk_markdown(markdown_content, parser_config)


def chunk_markdown(
    markdown_content: str, file_id: str, filename: str, processing_params: dict[str, Any]
) -> list[dict[str, Any]]:
    params = dict(processing_params or {})
    preset_id = normalize_chunk_preset_id(params.get("chunk_preset_id"))
    parser_config = params.get("chunk_parser_config") if isinstance(params.get("chunk_parser_config"), dict) else {}

    text_chunks = _dispatch_markdown_parser(preset_id, filename, markdown_content, parser_config)
    return _build_chunk_records(
        text_chunks,
        file_id,
        filename,
        markdown_content,
        processing_params=params,
    )


def chunk_file(
    file_content: str, file_id: str, filename: str, processing_params: dict[str, Any]
) -> list[dict[str, Any]]:
    # 当前链路中入库前均已转换为 markdown，因此与 chunk_markdown 保持同实现。
    return chunk_markdown(file_content, file_id, filename, processing_params)
