from platform_core.knowledge.training.lightrag_ablation import AblationInput
from platform_core.knowledge.training.lightrag_relation_review import (
    build_relation_completion_review_pack,
)


def test_relation_review_pack_contains_local_evidence_and_unsigned_human_fields():
    text = "脉冲压缩提高雷达距离分辨能力。"
    source = {"text": "脉冲压缩", "label": "KeyTechnology", "start": 0, "end": 4}
    target = {"text": "雷达距离分辨能力", "label": "Capability", "start": 6, "end": 14}
    baseline = {"entities": [source, target], "relations": []}
    enhanced = {
        "entities": [source, target],
        "relations": [
            {
                "source": source,
                "target": target,
                "label": "IMPROVES",
                "claim_level": "Fact",
                "confidence": 0.93,
                "evidence_spans": [{"start": 0, "end": len(text)}],
                "model_sources": ["lightrag_llm_gleaning"],
            }
        ],
    }

    pack = build_relation_completion_review_pack(
        [AblationInput(document_id="doc-1", block_id="block-1", text=text)],
        [baseline],
        [enhanced],
        source_report_sha256="a" * 64,
    )

    assert pack["candidate_count"] == 1
    assert pack["gold_status"] == "not_gold_pending_human_review"
    item = pack["items"][0]
    assert item["evidence"] == [{"start": 0, "end": len(text), "text": text}]
    assert item["matched_cues"] == ["提高"]
    assert item["human_review"]["decision"] is None
    assert item["review_status"] == "pending_human_review"
