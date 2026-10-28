"""在可终止的独立进程中运行迁移后的 SenseVoice 引擎。"""

import argparse
import asyncio
import json
import os
from pathlib import Path


async def main():
    """生成规范化文字稿 JSON，由平台 Worker 负责存储与任务状态。"""
    from platform_core.knowledge.video_transcriber.core.sensevoice_transcriber import SenseVoiceTranscriber
    from platform_core.knowledge.video_transcriber.models.schemas import Language
    from platform_core.knowledge.video_transcriber.utils.paragraph_formatter import format_paragraphs
    from platform_core.knowledge.video_transcriber.utils.text_normalizer import (
        normalize_english_spacing,
        strip_trailing_engagement_prompt,
    )
    from platform_core.knowledge.video_transcriber.model_loader import install_low_memory_loader

    install_low_memory_loader()

    parser = argparse.ArgumentParser()
    parser.add_argument("--punctuate", action="store_true")
    parser.add_argument("audio")
    parser.add_argument("output")
    parser.add_argument("language")
    args = parser.parse_args()
    os.environ["MODELSCOPE_CACHE"] = os.getenv("VIDEO_TRANSCRIBER_MODEL_CACHE", "./outputs/video-models")
    engine = SenseVoiceTranscriber(
        device=os.getenv("VIDEO_TRANSCRIBER_DEVICE", "cpu"),
        model_cache_dir=os.getenv("VIDEO_TRANSCRIBER_MODEL_CACHE", "./outputs/video-models"),
        chunk_duration_seconds=30,
        chunk_overlap_seconds=1,
        min_duration_for_chunking=30,
        timestamp_mode="none",
        enable_punctuation=False,
    )
    if args.punctuate:
        result_data = json.loads(Path(args.output).read_text(encoding="utf-8"))
        engine.enable_punctuation = True
        sections = []
        for paragraph in result_data["text"].split("\n\n"):
            sections.append(await asyncio.to_thread(engine._add_punctuation, paragraph, args.language))
        text = "\n\n".join(sections)
    else:
        result = await engine.transcribe_audio(args.audio, language=Language(args.language), timestamp_mode="none")
        paragraphs = format_paragraphs(result, silence_threshold=1.5, max_length=250, min_length=30)
        text = "\n\n".join(p.text for p in paragraphs if p.text.strip()) or result.text
        result_data = {"language": result.language, "confidence": result.confidence}
    text = strip_trailing_engagement_prompt(normalize_english_spacing(text))
    if not text.strip():
        raise ValueError("未识别到有效语音，请检查视频音轨或更换语言")
    Path(args.output).write_text(json.dumps({**result_data, "text": text}, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
