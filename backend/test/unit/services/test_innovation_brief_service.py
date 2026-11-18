import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from platform_core.services import innovation_brief_service
from platform_core.services.innovation_brief_service import (
    BRIEF_MAX_ITEMS,
    DEFAULT_TOPICS,
    PRIORITY_TECHNOLOGY_TAXONOMY,
    _advance_subscription_schedule,
    _assess_brief_quality,
    _await_research_explorer_result,
    _build_sections,
    _converge_research_digest_with_agent,
    _effective_significance_threshold,
    _expand_query_plan,
    _expand_query_plan_with_agent,
    _merge_hypothesis_candidates,
    _ground_research_digest,
    _parse_agent_query_plan,
    _parse_research_explorer_digest,
    _research_explorer_prompt,
    _score_and_classify,
    _select_high_value_evidence,
    _select_novel_hypotheses,
    _select_research_findings,
)
from platform_core.utils.datetime_utils import utc_now


def test_reminder_sensitivity_adjusts_and_clamps_threshold():
    assert _effective_significance_threshold(70, "conservative") == 80
    assert _effective_significance_threshold(70, "standard") == 70
    assert _effective_significance_threshold(70, "sensitive") == 60
    assert _effective_significance_threshold(95, "conservative") == 100
    assert _effective_significance_threshold(5, "sensitive") == 0


def test_scheduled_brief_advances_from_delivery_time_not_prepare_time():
    """提前准备不能把下一次运行仍计算为本次计划时刻。"""
    subscription = SimpleNamespace(
        daily_cron="0 8 * * *",
        weekly_cron="0 9 * * 1",
        timezone="Asia/Shanghai",
        next_daily_at=datetime(2026, 11, 10, 0, 0, tzinfo=UTC),
        next_weekly_at=datetime(2026, 11, 16, 1, 0, tzinfo=UTC),
    )

    _advance_subscription_schedule(
        subscription,
        "daily",
        scheduled_for=subscription.next_daily_at,
    )

    assert subscription.next_daily_at == datetime(2026, 11, 11, 0, 0, tzinfo=UTC)


def test_daily_and_weekly_always_run_research_explorer_when_enabled():
    low_signal = [{"score": 54, "change_signal": "new"}]
    meaningful_signal = [{"score": 60, "change_signal": "changed"}]

    assert innovation_brief_service._should_run_research_explorer(
        brief_type="daily", enabled=True, ranked=low_signal, significance_threshold=70
    )
    assert innovation_brief_service._should_run_research_explorer(
        brief_type="daily", enabled=True, ranked=meaningful_signal, significance_threshold=70
    )
    assert innovation_brief_service._should_run_research_explorer(
        brief_type="weekly", enabled=True, ranked=[], significance_threshold=70
    )
    assert not innovation_brief_service._should_run_research_explorer(
        brief_type="weekly", enabled=False, ranked=meaningful_signal, significance_threshold=70
    )
    assert not innovation_brief_service._should_run_research_explorer(
        brief_type="collection_update", enabled=True, ranked=meaningful_signal, significance_threshold=70
    )


def test_default_priority_taxonomy_covers_all_nineteen_directions_in_query_plan():
    assert len(PRIORITY_TECHNOLOGY_TAXONOMY) == 19
    assert DEFAULT_TOPICS == [row[0] for row in PRIORITY_TECHNOLOGY_TAXONOMY]

    plan = _expand_query_plan(
        SimpleNamespace(
            topics=DEFAULT_TOPICS,
            languages=["zh-CN", "en"],
            open_discovery_enabled=True,
        )
    )
    seed_queries = " ".join(row["query"] for row in plan if row["angle"].startswith("种子方向"))

    assert len(plan) == 12
    assert all(topic in seed_queries for topic in DEFAULT_TOPICS)
    assert "无人机、无人车、无人艇、无人潜航器、无人集群" in _research_explorer_prompt(
        {
            "name": "测试简报",
            "topics": DEFAULT_TOPICS,
            "keywords": [],
            "languages": ["zh-CN", "en"],
            "open_discovery_enabled": True,
        },
        plan,
    )


def test_seven_dimension_score_uses_fixed_weights():
    evidence = [
        {
            "id": "e-1",
            "title": "测试进展",
            "excerpt": "测试内容",
            "url": "https://example.com/report",
            "source": "Example",
            "source_type": "web_search",
            "review_status": "external",
            "pending_review": False,
        }
    ]

    ranked = _score_and_classify(evidence, {"topics": ["测试"], "keywords": []}, set())

    assert ranked[0]["score_breakdown"] == {
        "relevance": 55.0,
        "novelty": 90.0,
        "credibility": 62.0,
        "corroboration": 25.0,
        "disruption_potential": 30.0,
        "recency": 45.0,
        "innovation_expansion": 30.0,
    }
    assert ranked[0]["score"] == 51.4
    assert ranked[0]["recency_bucket"] == "unknown"
    assert ranked[0]["recency_days"] is None


def test_pending_review_evidence_never_becomes_fact():
    evidence = [
        {
            "id": "pending-official",
            "title": "官方试验通报",
            "excerpt": "无人系统试验",
            "url": "https://example.gov/report",
            "source": "Official",
            "source_type": "website",
            "review_status": "pending",
            "pending_review": True,
        }
    ]

    ranked = _score_and_classify(evidence, {"topics": ["无人系统"], "keywords": []}, set())

    assert ranked[0]["claim_level"] == "Inference"
    assert "等待审核" in ranked[0]["claim_reason"]


def test_recent_cross_domain_concept_softly_outranks_old_generic_research(monkeypatch):
    now = datetime(2026, 11, 9, 8, 0, tzinfo=UTC)
    monkeypatch.setattr(innovation_brief_service, "utc_now", lambda: now)
    evidence = [
        {
            "id": "recent",
            "title": "无人系统跨域分布式无源感知新概念",
            "excerpt": "提出异构节点与可变构型平台的跨域组合",
            "url": "https://journal.example.org/concept",
            "source": "Journal",
            "source_type": "web_search",
            "review_status": "external",
            "pending_review": False,
            "published_at": (now - timedelta(days=2)).isoformat(),
        },
        {
            "id": "old",
            "title": "无人系统智能控制研究",
            "excerpt": "论文讨论无人系统智能控制原理",
            "url": "https://journal.example.org/paper",
            "source": "Journal",
            "source_type": "web_search",
            "review_status": "external",
            "pending_review": False,
            "published_at": (now - timedelta(days=900)).date().isoformat(),
        },
    ]

    ranked = _score_and_classify(evidence, {"topics": ["无人系统"], "keywords": []}, set())

    assert [item["id"] for item in ranked] == ["recent", "old"]
    assert ranked[0]["score_breakdown"]["recency"] == 100.0
    assert ranked[0]["score_breakdown"]["innovation_expansion"] > 30.0
    assert ranked[1]["score_breakdown"]["recency"] == 15.0


def test_missing_or_future_published_at_is_not_treated_as_fresh(monkeypatch):
    now = datetime(2026, 11, 9, 8, 0, tzinfo=UTC)
    monkeypatch.setattr(innovation_brief_service, "utc_now", lambda: now)
    evidence = [
        {
            "id": "missing",
            "title": "未知日期信号",
            "excerpt": "缺少原始发布时间",
            "url": "https://example.org/missing",
            "source": "Example",
            "source_type": "web_search",
            "review_status": "external",
            "pending_review": False,
            "discovered_at": now.isoformat(),
        },
        {
            "id": "future",
            "title": "异常未来日期信号",
            "excerpt": "来源日期明显异常",
            "url": "https://example.net/future",
            "source": "Example",
            "source_type": "web_search",
            "review_status": "external",
            "pending_review": False,
            "published_at": (now + timedelta(days=30)).isoformat(),
        },
    ]

    ranked = _score_and_classify(evidence, {"topics": ["信号"], "keywords": []}, set())

    assert all(item["recency_bucket"] == "unknown" for item in ranked)
    assert all(item["recency_days"] is None for item in ranked)
    assert all(item["score_breakdown"]["recency"] == 45.0 for item in ranked)


def test_query_plan_keeps_seed_priority_and_adds_open_discovery_in_each_language():
    subscription = SimpleNamespace(
        topics=["无人系统"],
        languages=["zh-CN", "fr"],
        open_discovery_enabled=True,
    )

    plan = _expand_query_plan(subscription)

    assert len(plan) == 12
    assert {row["language"] for row in plan} == {"zh-CN", "fr"}
    assert any(row["angle"] == "种子方向·重点谱系新概念与关键进展" for row in plan)
    assert any(row["angle"] == "开放发现·跨域扫描与弱信号" for row in plan)
    assert any("量子感知" in row["query"] for row in plan)
    assert any("quantum sensing" in row["query"] for row in plan)
    assert all(str(utc_now().year) in row["query"] for row in plan)
    assert all("近7天 最新进展" in row["query"] for row in plan if row["language"] == "zh-CN")
    assert all("past 7 days latest update" in row["query"] for row in plan if row["language"] == "fr")
    assert all(" fr" in row["query"] for row in plan if row["language"] == "fr")

    weekly_plan = _expand_query_plan(
        SimpleNamespace(
            topics=["无人系统"],
            languages=["zh-CN", "en"],
            open_discovery_enabled=True,
            brief_type="weekly",
        )
    )
    assert all("近30天 最新进展" in row["query"] for row in weekly_plan if row["language"] == "zh-CN")
    assert all("past 30 days latest update" in row["query"] for row in weekly_plan if row["language"] == "en")


def test_custom_topic_does_not_disable_open_discovery_but_switch_can():
    enabled = _expand_query_plan(
        SimpleNamespace(
            topics=["定向能推进"],
            languages=["zh-CN"],
            open_discovery_enabled=True,
        )
    )
    disabled = _expand_query_plan(
        SimpleNamespace(
            topics=["定向能推进"],
            languages=["zh-CN"],
            open_discovery_enabled=False,
        )
    )

    assert any("定向能推进" in row["query"] for row in enabled)
    assert any("海底作战" in row["query"] for row in enabled)
    assert all(row["angle"].startswith("种子方向") for row in disabled)


async def test_web_collection_applies_daily_and_weekly_freshness_windows(monkeypatch):
    calls = []

    async def collect_source_items(_source_type, config, _context):
        calls.append(config)
        return []

    async def collect_knowledge_evidence(_kb_ids, _queries):
        return [], []

    class Context:
        async def set_progress(self, *_args):
            return None

    monkeypatch.setattr(innovation_brief_service, "collect_source_items", collect_source_items)
    monkeypatch.setattr(innovation_brief_service, "_collect_knowledge_evidence", collect_knowledge_evidence)
    base_snapshot = {"source_ids": [], "knowledge_ids": [], "tenant_id": "tenant-a"}
    plan = [{"query": "new equipment milestone"}]

    await innovation_brief_service._collect_evidence({**base_snapshot, "brief_type": "daily"}, plan, Context())
    await innovation_brief_service._collect_evidence({**base_snapshot, "brief_type": "weekly"}, plan, Context())

    assert [call["time_range"] for call in calls] == ["week", "month"]


async def test_agent_query_planner_reuses_platform_model_and_keeps_baseline(monkeypatch):
    calls = []

    class Model:
        async def ainvoke(self, messages, config):
            calls.append((messages, config))
            return SimpleNamespace(
                content=(
                    '[{"topic":"无人系统","language":"en","angle":"supply chain",'
                    '"query":"unmanned systems critical components 2026"}]'
                )
            )

    monkeypatch.setattr("platform_core.models.chat.load_chat_model", lambda *_args, **_kwargs: Model())
    subscription = {
        "topics": ["无人系统"],
        "keywords": ["集群"],
        "languages": ["zh-CN", "en"],
    }

    plan, warnings = await _expand_query_plan_with_agent(
        subscription,
        model_spec="provider:model",
        run_id="run-1",
    )

    assert warnings == []
    assert plan[0]["angle"] == "supply chain"
    assert {row["language"] for row in plan} == {"zh-CN", "en"}
    assert calls[0][1]["tags"] == ["innovation-brief", "query-planning"]
    planner_payload = calls[0][0][1].content
    assert '"open_discovery_enabled": true' in planner_payload
    assert "量子感知、通信与先进传感" in planner_payload


def test_two_independent_sources_can_promote_same_topic_to_fact():
    evidence = [
        {
            "id": "a",
            "title": "无人系统完成新试验",
            "excerpt": "无人系统集群验证",
            "url": "https://source-a.example/report",
            "source": "A",
            "source_type": "web_search",
            "review_status": "external",
            "pending_review": False,
        },
        {
            "id": "b",
            "title": "集群平台公布验证结果",
            "excerpt": "独立报道无人系统试验",
            "url": "https://source-b.example/article",
            "source": "B",
            "source_type": "web_search",
            "review_status": "external",
            "pending_review": False,
        },
    ]

    ranked = _score_and_classify(evidence, {"topics": ["无人系统"], "keywords": []}, set())

    assert all(item["claim_level"] == "Fact" for item in ranked)
    assert all(item["independent_source_count"] == 2 for item in ranked)


def test_changed_and_conflicting_evidence_get_explicit_signals():
    history = [
        {
            "id": "old",
            "title": "无人系统试验成功",
            "excerpt": "官方确认完成部署试验",
            "url": "https://example.test/report",
            "source": "Example",
            "fingerprint": "old-fingerprint",
        }
    ]
    current = [
        {
            "id": "new",
            "title": "无人系统试验失败",
            "excerpt": "项目方否认完成部署并宣布推迟",
            "url": "https://example.test/report",
            "source": "Example",
            "source_type": "web_search",
            "review_status": "external",
            "pending_review": False,
        }
    ]

    ranked = _score_and_classify(current, {"topics": ["无人系统"], "keywords": []}, history)

    assert ranked[0]["change_signal"] == "conflict"
    assert ranked[0]["score_breakdown"]["novelty"] == 100.0
    assert ranked[0]["historical_fingerprint"] == "old-fingerprint"


def test_brief_selects_at_most_ten_new_high_value_items_without_in_run_duplicates():
    ranked = [
        {
            "id": f"e-{index}",
            "title": "重复技术" if index in {1, 2} else f"高价值技术 {index}",
            "url": f"https://example.test/{index}",
            "score": 100 - index,
            "change_signal": "known" if index == 0 else "new",
        }
        for index in range(15)
    ]

    selected = _select_high_value_evidence(ranked)

    assert len(selected) == BRIEF_MAX_ITEMS
    assert all(item["change_signal"] != "known" for item in selected)
    assert sum(item["title"] == "重复技术" for item in selected) == 1
    assert selected == sorted(selected, key=lambda item: item["score"], reverse=True)


def test_brief_prioritizes_source_diversity_before_filling_remaining_slots():
    ranked = [
        {"title": "A1", "url": "https://source-a.test/1", "score": 99, "change_signal": "new"},
        {"title": "A2", "url": "https://source-a.test/2", "score": 98, "change_signal": "new"},
        {"title": "A3", "url": "https://source-a.test/3", "score": 97, "change_signal": "new"},
        {"title": "B1", "url": "https://source-b.test/1", "score": 96, "change_signal": "new"},
    ]

    selected = _select_high_value_evidence(ranked, limit=3)

    assert [item["title"] for item in selected] == ["A1", "A2", "B1"]


def test_brief_deduplicates_hypotheses_and_research_findings_across_daily_and_weekly():
    hypotheses = [
        {"hypothesis_id": "old", "mechanism_hypothesis": "历史假设"},
        {"hypothesis_id": "new", "mechanism_hypothesis": "新增假设"},
        {"hypothesis_id": "new", "mechanism_hypothesis": "新增假设重复"},
    ]
    findings = [
        {"title": "历史技术"},
        {"title": "新增技术"},
        {"title": "新增 技术"},
    ]

    selected_hypotheses = _select_novel_hypotheses(
        hypotheses,
        historical_keys={"id:old"},
    )
    selected_findings = _select_research_findings(
        findings,
        historical_titles={"历史技术"},
    )

    assert [item["hypothesis_id"] for item in selected_hypotheses] == ["new"]
    assert [item["title"] for item in selected_findings] == ["新增技术"]


def test_agent_query_parser_accepts_langchain_content_blocks():
    rows = _parse_agent_query_plan(
        [
            {
                "type": "text",
                "text": (
                    '```json\n{"queries":[{"topic":"反无人系统","language":"en",'
                    '"angle":"countermeasure","query":"counter UAS directed energy"}]}\n```'
                ),
            }
        ]
    )

    assert rows == [
        {
            "topic": "反无人系统",
            "language": "en",
            "angle": "countermeasure",
            "query": "counter UAS directed energy",
        }
    ]


def test_agent_query_parser_recovers_rows_from_commentary_and_truncated_array():
    rows = _parse_agent_query_plan(
        '已完成查询规划：\n[{"topic":"气凝胶","language":"zh-CN","angle":"技术迁移",'
        '"query":"气凝胶 装备概念创新"},{"topic":"热防护","language":"en",'
        '"angle":"weak signal","query":"aerogel defense thermal protection"},'
    )

    assert [row["topic"] for row in rows] == ["气凝胶", "热防护"]


def test_grounding_rejects_hallucinated_urls_and_rechecks_fact_level():
    digest = _parse_research_explorer_digest(
        '{"summary":"完成","findings":['
        '{"title":"白名单发现","principle":"相变吸热","why_it_matters":"降低热特征",'
        '"equipment_implication":"形成轻量热防护壳体","maturity":"样机",'
        '"evidence":"输入证据支持","boundaries":"循环寿命待验证","claim_level":"Fact",'
        '"sources":[{"title":"允许来源","url":"https://allowed.example/report"},'
        '{"title":"伪造来源","url":"https://invented.example/paper"}]},'
        '{"title":"仅伪造来源","principle":"未知","claim_level":"Fact",'
        '"sources":[{"title":"伪造来源","url":"https://invented.example/only"}]}],'
        '"innovation_hypotheses":[{"title":"轻量热防护弹体","mechanism_hypothesis":"组合机理",'
        '"equipment_concept":"单一弹体","operational_value":"扩展热环境包线",'
        '"feasibility_basis":"白名单发现","verification_path":"热循环试验",'
        '"countermeasures_and_risks":"烧蚀与老化","source_titles":["白名单发现"]}],"gaps":[]}'
    )

    grounded = _ground_research_digest(
        digest,
        [{"title": "允许来源", "url": "https://allowed.example/report"}],
    )

    assert [item["title"] for item in grounded["findings"]] == ["白名单发现"]
    assert grounded["findings"][0]["claim_level"] == "Inference"
    assert grounded["untrusted_source_rejected_count"] == 2
    assert grounded["innovation_hypotheses"][0]["source_titles"] == ["白名单发现"]


def test_grounding_accepts_registered_doi_for_direct_paper_fact():
    digest = _parse_research_explorer_digest(
        '{"summary":"完成","findings":[{'
        '"title":"冰面 DAS 外场试验","principle":"以冰面光纤阵列接收水下声源",'
        '"why_it_matters":"可形成寒区水下警戒的新部署方式",'
        '"equipment_implication":"牵引冰面光纤警戒组件",'
        '"maturity":"地面试验","evidence":"论文直接报告外场试验结果",'
        '"boundaries":"跨海况性能仍待验证","claim_level":"Fact",'
        '"sources":[{"title":"原始论文",'
        '"url":"https://doi.org/10.1109/ICICN71760.2026.11745001"}]}],"gaps":[]}'
    )

    grounded = _ground_research_digest(
        digest,
        [
            {
                "title": "原始论文",
                "url": "https://doi.org/10.1109/ICICN71760.2026.11745001",
            }
        ],
    )

    assert grounded["findings"][0]["claim_level"] == "Fact"


def test_quality_gate_requires_all_four_grounded_layers():
    empty = _assess_brief_quality(
        {
            "research_explorer_findings": [],
            "confirmed_facts": [],
            "cross_validated_inferences": [],
            "innovation_hypotheses": [],
        }
    )
    finding = {
        "title": "技术发现",
        "principle": "作用原理",
        "evidence": "证据摘要",
        "equipment_implication": "具体装备影响",
        "boundaries": "失效边界",
        "sources": [{"url": "https://source.example/report"}],
    }
    complete = _assess_brief_quality(
        {
            "research_explorer_findings": [
                {**finding, "title": "发现一"},
                {**finding, "title": "发现二"},
                {**finding, "title": "发现三"},
            ],
            "confirmed_facts": [{"title": "事实"}],
            "cross_validated_inferences": [{"title": "推断"}],
            "innovation_hypotheses": [
                {
                    "mechanism_hypothesis": "组合机理",
                    "equipment_concept": "单一具体装备",
                    "operational_value": "改变任务关系",
                    "verification_path": "最小试验",
                    "countermeasures_and_risks": "反制风险",
                    "source_titles": ["发现一"],
                }
            ],
        }
    )

    assert empty["passed"] is False
    assert len(empty["failures"]) == 4
    assert complete["passed"] is True


async def test_convergence_agent_uses_only_candidate_evidence_urls(monkeypatch):
    response_json = {
        "summary": "完成收敛",
        "findings": [
            {
                "title": f"发现{index}",
                "principle": "新材料热传导调控原理",
                "why_it_matters": "改变装备热管理包线",
                "equipment_implication": "形成轻量化热防护组件",
                "maturity": "样机",
                "published_at": "2026-11-10",
                "claim_level": "Inference",
                "evidence": "输入证据支持",
                "boundaries": "环境稳定性待验证",
                "sources": [
                    {"title": "输入来源", "url": "https://allowed.example/report"},
                    {"title": "模型臆造", "url": "https://invented.example/paper"},
                ],
            }
            for index in range(1, 4)
        ],
        "innovation_hypotheses": [
            {
                "title": "气凝胶自适应热防护弹体",
                "mechanism_hypothesis": "将气凝胶隔热与可调热导结构组合",
                "equipment_concept": "单一具体的自适应热防护弹体",
                "operational_value": "扩展高热流环境任务包线",
                "feasibility_basis": "发现1支持材料基础",
                "verification_path": "开展缩比热流循环试验",
                "countermeasures_and_risks": "材料脆性与循环老化",
                "source_titles": ["发现1"],
            }
        ],
        "gaps": [],
    }

    class Model:
        async def ainvoke(self, _messages, config):
            assert config["tags"] == ["innovation-brief", "quality-convergence"]
            return SimpleNamespace(content=innovation_brief_service.json.dumps(response_json, ensure_ascii=False))

    monkeypatch.setattr("platform_core.models.chat.load_chat_model", lambda *_args, **_kwargs: Model())
    digest, warnings = await _converge_research_digest_with_agent(
        {
            "name": "气凝胶技术观察",
            "brief_type": "daily",
            "topics": ["气凝胶"],
            "keywords": ["热防护"],
        },
        [
            {
                "title": "输入来源",
                "url": "https://allowed.example/report",
                "source": "Example",
                "excerpt": "气凝胶样机完成热防护试验",
                "claim_level": "Inference",
            }
        ],
        {},
        model_spec="provider:model",
        run_id="run-1",
        attempt=1,
        quality_failures=["合格调研发现不足"],
    )

    assert warnings == []
    assert len(digest["findings"]) == 3
    assert all(
        source["url"] == "https://allowed.example/report"
        for finding in digest["findings"]
        for source in finding["sources"]
    )
    assert digest["untrusted_source_rejected_count"] == 3
    assert digest["innovation_hypotheses"][0]["title"] == "气凝胶自适应热防护弹体"


async def test_convergence_agent_can_reuse_deep_research_source_whitelist(monkeypatch):
    source_url = "https://doi.org/10.1109/ICICN71760.2026.11745001"
    response_json = {
        "summary": "完成收敛",
        "findings": [
            {
                "title": "冰面 DAS 外场试验",
                "principle": "以冰面光纤阵列接收水下声源",
                "why_it_matters": "形成寒区水下警戒的新部署方式",
                "equipment_implication": "牵引冰面光纤警戒组件",
                "maturity": "地面试验",
                "published_at": "2026-11-10",
                "claim_level": "Fact",
                "evidence": "原始论文直接报告外场试验结果",
                "boundaries": "跨海况性能仍待验证",
                "sources": [{"title": "原始论文", "url": source_url}],
            }
        ],
        "innovation_hypotheses": [],
        "gaps": [],
    }

    class Model:
        async def ainvoke(self, messages, config):
            assert config["tags"] == ["innovation-brief", "quality-convergence"]
            assert source_url in messages[1].content
            return SimpleNamespace(content=innovation_brief_service.json.dumps(response_json, ensure_ascii=False))

    monkeypatch.setattr("platform_core.models.chat.load_chat_model", lambda *_args, **_kwargs: Model())
    digest, warnings = await _converge_research_digest_with_agent(
        {
            "name": "水下感知观察",
            "brief_type": "daily",
            "topics": ["水下感知"],
            "keywords": ["DAS"],
        },
        [],
        {
            "findings": [
                {
                    "title": "冰面 DAS 外场试验",
                    "principle": "以冰面光纤阵列接收水下声源",
                    "evidence": "原始论文直接报告外场试验结果",
                    "maturity": "地面试验",
                    "claim_level": "Fact",
                    "sources": [{"title": "原始论文", "url": source_url}],
                }
            ]
        },
        model_spec="provider:model",
        run_id="run-1",
        attempt=1,
        quality_failures=["已证实事实不足"],
    )

    assert warnings == []
    assert digest["findings"][0]["claim_level"] == "Fact"


def test_research_explorer_prompt_prioritizes_strike_technologies_without_hard_boundary():
    snapshot = {
        "name": "新质技术观察",
        "brief_type": "weekly",
        "topics": ["远程精确打击"],
        "keywords": ["制导"],
        "languages": ["zh-CN", "en"],
        "open_discovery_enabled": True,
        "recent_brief_titles": ["昨日已报技术"],
        "candidate_signals": [{"title": "待核验高分信号", "url": "https://example.test/signal", "score": 88}],
    }

    prompt = _research_explorer_prompt(snapshot, [{"query": "precision strike"}])

    assert "必须调用 research-explorer" in prompt
    assert "2 至 3 个并行分片" in prompt
    assert "research_budget_mode 使用 standard" in prompt
    assert "最多 3 个" in prompt
    assert "fact-verifier" in prompt
    assert "19 类新质武器装备技术谱系" in prompt
    assert "不是范围边界" in prompt
    assert "作用原理" in prompt
    assert "昨日已报技术" in prompt
    assert "待核验高分信号" in prompt
    assert "优先核验 candidate_signals" in prompt
    assert "近30天优先、必要时回溯近90天" in prompt
    assert "持续扫描谱系外的新概念" in prompt
    assert "不得成为发现范围、准入门槛或唯一优先方向" in prompt
    assert "不得因信号仍处论文、仿真或概念阶段而过滤" in prompt
    assert "装备作用机理、总体构型、接敌几何、任务链位置" in prompt
    assert "弱化营销稿、转载和没有具体机理的泛化 AI/无人化" in prompt
    assert "innovation_outlook" in prompt
    assert "新质技术思考与可探索组合" in prompt
    assert "精选最多 8 条" in prompt
    assert "跨技术或跨原理组合" in prompt
    assert "新质装备形态" in prompt
    assert "最小可验证试验" in prompt
    assert "反制、风险、失效边界" in prompt
    assert "source_titles" in prompt

    snapshot["brief_type"] = "daily"
    daily_prompt = _research_explorer_prompt(snapshot, [{"query": "precision strike"}])
    assert "1 至 2 个并行分片" in daily_prompt
    assert "最多 2 个" in daily_prompt


def test_research_explorer_digest_preserves_principle_sources_and_claim_layer():
    digest = _parse_research_explorer_digest(
        '{"summary":"发现跨域弱信号","innovation_outlook":"可将量子惯导与任务接续架构组合",'
        '"findings":[{"title":"量子惯导",'
        '"principle":"利用原子干涉测量惯性变化","why_it_matters":"降低卫星拒止影响",'
        '"equipment_implication":"形成无卫星依赖的远程打击组合导航组件",'
        '"maturity":"样机","published_at":"2026-11-06",'
        '"claim_level":"Inference","evidence":"原理样机已有论文证据",'
        '"boundaries":"体积与环境稳定性待验证","sources":[{"title":"论文",'
        '"url":"https://example.org/paper"}]}],"gaps":["缺少外场数据"]}'
    )

    assert digest["findings"][0]["title"] == "量子惯导"
    assert digest["innovation_outlook"] == "可将量子惯导与任务接续架构组合"
    assert digest["findings"][0]["claim_level"] == "Inference"
    assert digest["findings"][0]["equipment_implication"] == "形成无卫星依赖的远程打击组合导航组件"
    assert digest["findings"][0]["maturity"] == "样机"
    assert digest["findings"][0]["published_at"] == "2026-11-06"
    assert digest["findings"][0]["sources"][0]["url"] == "https://example.org/paper"
    assert digest["gaps"] == ["缺少外场数据"]


def test_research_explorer_digest_enforces_fact_source_gate_and_drops_unsourced_findings():
    digest = _parse_research_explorer_digest(
        '{"summary":"完成","findings":['
        '{"title":"单一报道","principle":"原理 A","claim_level":"Fact",'
        '"sources":[{"title":"报道","url":"https://news.example/a"}]},'
        '{"title":"双源印证","principle":"原理 B","claim_level":"Fact",'
        '"sources":[{"title":"来源一","url":"https://one.example/b"},'
        '{"title":"来源二","url":"https://two.example/b"}]},'
        '{"title":"无来源结论","principle":"原理 C","claim_level":"Inference","sources":[]}'
        '],"gaps":[]}'
    )

    assert [item["claim_level"] for item in digest["findings"]] == ["Inference", "Fact"]
    assert any("无来源结论" in gap for gap in digest["gaps"])


def test_research_explorer_digest_builds_evidence_grounded_innovation_hypothesis():
    digest = _parse_research_explorer_digest(
        '{"summary":"完成","findings":[{"title":"分布式无源感知",'
        '"principle":"多节点协同形成无源测向基线","claim_level":"Inference",'
        '"sources":[{"title":"试验报告","url":"https://example.org/sensor"}]}],'
        '"innovation_hypotheses":[{"title":"可抛撒协同无源感知弹",'
        '"mechanism_hypothesis":"将可抛撒节点与协同测向组合形成末段目标更新",'
        '"equipment_concept":"由远程平台投送的低成本感知节点群",'
        '"operational_value":"在主探测链受损时接续目标定位",'
        '"feasibility_basis":"分布式无源感知已出现外场试验信号",'
        '"verification_path":"先以三节点缩比场验证定位误差与组网时间",'
        '"countermeasures_and_risks":"受节点同步误差、诱骗与回传压制影响",'
        '"source_titles":["分布式无源感知"]}],"gaps":[]}'
    )

    hypothesis = digest["innovation_hypotheses"][0]
    assert hypothesis["title"] == "可抛撒协同无源感知弹"
    assert hypothesis["claim_level"] == "Hypothesis"
    assert hypothesis["source_titles"] == ["分布式无源感知"]
    assert hypothesis["feasibility_basis"] == ["分布式无源感知已出现外场试验信号"]
    assert hypothesis["hypothesis_id"].startswith("research-")


def test_research_explorer_digest_rejects_unanchored_or_incomplete_hypothesis():
    digest = _parse_research_explorer_digest(
        '{"summary":"完成","findings":[{"title":"已核验发现","principle":"原理",'
        '"sources":[{"title":"来源","url":"https://example.org/source"}]}],'
        '"innovation_hypotheses":[{"title":"无依据设想","mechanism_hypothesis":"待验证机理",'
        '"equipment_concept":"装备形态","operational_value":"作战价值",'
        '"feasibility_basis":"模型推演","verification_path":"缩比试验",'
        '"countermeasures_and_risks":"存在风险","source_titles":["不存在的发现"]},'
        '{"title":"字段不全设想","mechanism_hypothesis":"待验证机理",'
        '"source_titles":["已核验发现"]}],"gaps":[]}'
    )

    assert digest["innovation_hypotheses"] == []
    assert any("无依据设想" in gap and "未引用" in gap for gap in digest["gaps"])
    assert any("字段不全设想" in gap and "缺少字段" in gap for gap in digest["gaps"])


def test_research_hypotheses_fill_innovation_section_when_graph_has_no_candidates():
    research_hypothesis = {
        "hypothesis_id": "research-a",
        "title": "调研驱动设想",
        "claim_level": "Hypothesis",
    }

    merged = _merge_hypothesis_candidates({"innovation_hypotheses": [research_hypothesis]}, [])
    selected = _select_novel_hypotheses(merged, historical_keys=set())

    assert selected == [research_hypothesis]


async def test_knowledge_evidence_searches_multiple_libraries_with_bounded_concurrency(monkeypatch):
    active = 0
    max_active = 0

    async def query_knowledge(query, *, kb_id):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return [{"id": f"{kb_id}:{query}", "title": kb_id, "content": query}]

    monkeypatch.setattr(innovation_brief_service.knowledge_base, "aquery", query_knowledge)

    evidence, warnings = await innovation_brief_service._collect_knowledge_evidence(
        [f"kb-{index}" for index in range(6)],
        ["query"],
    )

    assert warnings == []
    assert len(evidence) == 6
    assert max_active == innovation_brief_service.BRIEF_KNOWLEDGE_CONCURRENCY


def test_research_explorer_digest_extracts_json_surrounded_by_agent_commentary():
    digest = _parse_research_explorer_digest(
        '简报已完成。以下为最终 JSON：\n{"summary":"跨域扫描完成","findings":[{'
        '"title":"旋转爆震推进","principle":"以爆震波代替常规爆燃",'
        '"claim_level":"Inference","sources":[{"title":"原始来源",'
        '"url":"https://example.org/source"}]}],"gaps":[]}\nJSON 已写入成果目录。'
    )

    assert digest["summary"] == "跨域扫描完成"
    assert digest["findings"][0]["title"] == "旋转爆震推进"
    assert digest["findings"][0]["sources"][0]["url"] == "https://example.org/source"


def test_research_explorer_digest_recovers_complete_items_from_truncated_json():
    digest = _parse_research_explorer_digest(
        '{"summary":"跨域扫描","findings":[{'
        '"title":"旋转爆震推进","principle":"爆震增压",'
        '"claim_level":"Inference","sources":[{'
        '"title":"论文","url":"https://example.org/paper"}]}],'
        '"innovation_hypotheses":[{'
        '"title":"爆震推进巡飞平台","mechanism_hypothesis":"推进与任务规划耦合",'
        '"equipment_concept":"可变航程巡飞平台","operational_value":"扩大任务包线",'
        '"feasibility_basis":"旋转爆震推进发现",'
        '"verification_path":"缩比台架试验",'
        '"countermeasures_and_risks":"热管理失效",'
        '"source_titles":["旋转爆震推进"]}],"gaps":['
    )

    assert digest["summary"] == "跨域扫描"
    assert [item["title"] for item in digest["findings"]] == ["旋转爆震推进"]
    assert [item["title"] for item in digest["innovation_hypotheses"]] == ["爆震推进巡飞平台"]
    assert any("截断" in gap for gap in digest["gaps"])


def test_research_findings_are_projected_into_fact_and_inference_sections():
    digest = {
        "summary": "完成",
        "innovation_outlook": "由试验结果进一步探索可重构任务载荷",
        "findings": [
            {
                "title": "官方试验完成",
                "principle": "验证关键机理",
                "evidence": "官方发布试验结果",
                "why_it_matters": "提高成熟度",
                "equipment_implication": "牵引形成新型任务载荷",
                "maturity": "飞行/海试",
                "published_at": "2026-11-08",
                "boundaries": "仍需扩大样本",
                "claim_level": "Fact",
                "sources": [{"title": "官方", "url": "https://example.gov/test"}],
            },
            {
                "title": "任务链影响",
                "principle": "由试验结果推演体系影响",
                "claim_level": "Inference",
                "sources": [{"title": "论文", "url": "https://example.org/paper"}],
            },
        ],
    }

    sections = _build_sections([], [], [], research_digest=digest)

    assert [item["title"] for item in sections["confirmed_facts"]] == ["官方试验完成"]
    assert [item["title"] for item in sections["cross_validated_inferences"]] == ["任务链影响"]
    assert sections["confirmed_facts"][0]["url"] == "https://example.gov/test"
    assert sections["confirmed_facts"][0]["maturity"] == "飞行/海试"
    assert sections["confirmed_facts"][0]["published_at"] == "2026-11-08"
    assert "牵引形成新型任务载荷" in sections["confirmed_facts"][0]["excerpt"]
    assert sections["research_explorer_outlook"] == "由试验结果进一步探索可重构任务载荷"


async def test_research_explorer_continues_polling_after_generic_sse_timeout(monkeypatch):
    from platform_core.services.agent_run_service import AgentRunWaitTimeout

    polls = []

    async def await_result(**_kwargs):
        raise AgentRunWaitTimeout({"agent_run_id": "agent-run-1", "status": "running"})

    async def load_result(**_kwargs):
        polls.append(True)
        return {"agent_run_id": "agent-run-1", "status": "completed", "output": "{}"}

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(
        "platform_core.services.agent_run_service.await_agent_run_result",
        await_result,
    )
    monkeypatch.setattr(
        "platform_core.services.agent_run_service.load_agent_run_result",
        load_result,
    )
    monkeypatch.setattr(innovation_brief_service.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(innovation_brief_service, "BRIEF_RESEARCH_EXPLORER_RECHECK_SECONDS", 0.01)
    monkeypatch.setattr(innovation_brief_service, "_research_explorer_wait_budget_seconds", lambda _value: 1)

    result = await _await_research_explorer_result(
        run_id="agent-run-1",
        current_uid="owner-a",
        scheduled_for=None,
    )

    assert result["status"] == "completed"
    assert polls == [True]


async def test_scheduled_research_explorer_runs_without_interactive_tool_approval(monkeypatch):
    captured = {}

    class FakeDb:
        async def scalar(self, _statement):
            return SimpleNamespace(uid="owner-a", is_deleted=0)

    class FakeManager:
        @asynccontextmanager
        async def get_async_session_context(self):
            yield FakeDb()

    async def submit_agent_request(*, request_input, **_kwargs):
        captured["request_input"] = request_input
        return {"run_id": "agent-run-1"}

    async def await_agent_run_result(**_kwargs):
        return {
            "status": "completed",
            "agent_slug": "deep-research",
            "output": '{"summary":"完成","findings":[],"gaps":[]}',
        }

    monkeypatch.setattr(innovation_brief_service, "pg_manager", FakeManager())
    monkeypatch.setattr(
        "platform_core.services.agent_request_service.submit_agent_request",
        submit_agent_request,
    )
    monkeypatch.setattr(
        "platform_core.services.agent_run_service.await_agent_run_result",
        await_agent_run_result,
    )

    digest, warnings = await innovation_brief_service._collect_research_explorer_digest(
        {
            "owner_uid": "owner-a",
            "name": "新质技术观察",
            "topics": ["无人系统"],
            "keywords": ["自主"],
            "languages": ["zh-CN"],
            "knowledge_ids": [],
            "open_discovery_enabled": True,
        },
        [{"query": "autonomous systems"}],
        run_id="brief-run-1",
    )

    assert warnings == []
    assert digest["agent_run_id"] == "agent-run-1"
    assert captured["request_input"].tool_approval_mode == "always_trust"
