# Phase 7 联网工具与证据治理实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现公开网络广泛搜集、网页抓取、正文简化、材料化、证据评分、去重、独立印证、冲突检测和反证保留，并完成真实联网 smoke。

**Architecture:** 搜索层允许多个 provider 聚合结果，不按域名硬阻断；网络层只执行安全边界；证据层根据内容质量决定 candidate/accepted/rejected。所有网页正文先写 artifact，再从精确位置构造 EvidenceCard，模型口述 URL 不直接成为证据。

**Tech Stack:** requests、BeautifulSoup4、asyncio.to_thread、hashlib、ipaddress、pytest HTTP fixture。

## Global Constraints

- 仅允许 `http/https`，拒绝 loopback、私网、link-local、metadata IP 和非标准危险跳转。
- 单响应默认最大 5MB，默认超时 15 秒，每 host 并发 2、最小间隔 300ms。
- 搜索结果不是证据，抓取并定位正文后才可创建 EvidenceCard。
- 质量分低于 0.62 的材料不能支撑正式 claim，但要保留拒绝原因。
- 高置信关键 claim 至少需要两个独立来源，或明确标记单源限制。
- EvidenceCard API 投影必须包含评分分解、decision status、conflict group、claim refs、source location 和 artifact metadata，正文通过受控 artifact 接口按需加载。

---

### Task 1: 实现网络安全、限速和缓存

**Files:**
- Create: `src/equipment_deep_research/tools/security.py`
- Create: `src/equipment_deep_research/tools/fetch.py`
- Test: `tests/equipment_deep_research/unit/test_network_security.py`
- Test: `tests/equipment_deep_research/integration/test_fetch_tool.py`

**Interfaces:**
- Produces: `UrlSecurityPolicy.validate()`、`DomainRateLimiter`、`FetchClient.fetch()`、`FetchResult`。

- [ ] **Step 1: 写安全失败测试**

```python
@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "http://127.0.0.1/a", "http://169.254.169.254/latest/meta-data",
    "http://10.0.0.1/", "ftp://example.com/file",
])
def test_unsafe_urls_are_rejected(url: str) -> None:
    with pytest.raises(UnsafeUrlError):
        UrlSecurityPolicy().validate(url)

def test_public_domain_is_not_rejected_by_content_allowlist() -> None:
    UrlSecurityPolicy(resolver=lambda _: ["93.184.216.34"]).validate("https://example.com/research")
```

- [ ] **Step 2: 运行并确认失败**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_network_security.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现安全抓取**

每次 redirect 重新解析并校验 IP；响应流式读取并在超过 `max_response_bytes` 时终止；缓存 key 为规范 URL + Accept-Language；记录状态码、content type、hash、抓取时间和最终 URL。

- [ ] **Step 4: 运行网络和 fetch fixture 测试**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_network_security.py tests/equipment_deep_research/integration/test_fetch_tool.py -q`

Expected: PASS。

- [ ] **Step 5: 验证失败诊断材料化**

Run: `python3 -m pytest tests/equipment_deep_research/integration/test_fetch_tool.py -q -k diagnostic`

Expected: DNS、超时、过大响应和非文本响应均有结构化错误和 artifact 元数据。

### Task 2: 实现多 provider 聚合搜索

**Files:**
- Create: `src/equipment_deep_research/tools/search.py`
- Modify: `configs/equipment_deep_research/tools.yaml`
- Test: `tests/equipment_deep_research/unit/test_search_aggregation.py`

**Interfaces:**
- Produces: `SearchProvider`、`SearchHit`、`SearchAggregator.search()`、`StaticSearchProvider`、`SearxngSearchProvider`、`ResponsesWebSearchProvider`。

- [ ] **Step 1: 写失败测试**

```python
@pytest.mark.asyncio
async def test_aggregator_merges_and_deduplicates_providers() -> None:
    aggregator = SearchAggregator([provider_a_same_url(), provider_b_same_url_and_new_url()])
    hits = await aggregator.search("低空无人机 探测 抗干扰", limit=10)
    assert len(hits) == 2
    assert hits[0].provider_names == ["a", "b"]

@pytest.mark.asyncio
async def test_search_does_not_filter_unknown_public_domain() -> None:
    hits = await SearchAggregator([static_provider("https://research.example.org/a")]).search("test")
    assert hits[0].url == "https://research.example.org/a"
```

- [ ] **Step 2: 运行并确认失败**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_search_aggregation.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现 provider 协议和聚合排序**

先按规范 URL 去重，再按 query 相关性、provider rank 和跨 provider 重合度排序。可用 provider 由环境配置决定；一个 provider 失败不终止其他 provider，并在 round summary 记录降级。

- [ ] **Step 4: 运行聚合搜索测试**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_search_aggregation.py -q`

Expected: PASS。

- [ ] **Step 5: 验证查询日志脱敏**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_search_aggregation.py -q -k redaction`

Expected: API key 和完整 headers 不进入 SearchHit、trace 或 session。

### Task 3: 实现正文简化和精确位置索引

**Files:**
- Create: `src/equipment_deep_research/tools/simplify.py`
- Rewrite: `src/equipment_deep_research/tools/materialization.py`
- Test: `tests/equipment_deep_research/unit/test_page_simplification.py`
- Fixture: `tests/equipment_deep_research/fixtures/article_with_noise.html`

**Interfaces:**
- Produces: `SimplifiedPage`、`ParagraphRef`、`simplify_html()`、`paragraph_at()`、`EvidenceMaterializer.materialize_page()`。

- [ ] **Step 1: 写失败测试**

```python
def test_simplifier_removes_navigation_and_keeps_article_metadata(tmp_path: Path) -> None:
    page = simplify_html(load_fixture("article_with_noise.html"), artifact_store(tmp_path))
    assert "导航" not in page.text
    assert page.title == "测试文章"
    assert page.published_at == "2026-06-01"
    assert page.paragraphs[1].location.startswith(page.simplified_artifact_ref)
    assert paragraph_at(page.paragraphs[1].location)
```

- [ ] **Step 2: 运行并确认失败**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_page_simplification.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现正文提取**

移除 script/style/nav/footer/aside，优先 article/main，按文本密度选择正文根节点；输出标题、作者/机构、发布时间、段落列表、raw/simplified artifact refs 和内容 hash。

- [ ] **Step 4: 运行正文测试**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_page_simplification.py -q`

Expected: PASS。

- [ ] **Step 5: 验证 EvidenceCard excerpt 可从 location 复现**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_page_simplification.py -q -k evidence_location`

Expected: PASS。

### Task 4: 实现证据评分、去重、印证和冲突检测

**Files:**
- Create: `src/equipment_deep_research/tools/evidence_filter.py`
- Modify: `src/equipment_deep_research/domain/models.py`
- Test: `tests/equipment_deep_research/unit/test_evidence_filter.py`

**Interfaces:**
- Produces: `EvidenceQualityScore`、`EvidenceDecision`、`EvidenceFilter.evaluate()`、`corroborate()`、`detect_conflicts()`。

- [ ] **Step 1: 写失败测试固定评分公式**

```python
def test_quality_score_uses_configured_weights() -> None:
    score = scorer.score(relevance=1.0, transparency=0.8, freshness=0.6, direct_support=0.9, extraction_quality=1.0)
    assert score.total == pytest.approx(0.30 + 0.12 + 0.09 + 0.225 + 0.15)

def test_low_quality_lead_is_rejected_but_retained() -> None:
    decision = evidence_filter.evaluate(card(score=0.51))
    assert decision.status == "rejected"
    assert decision.reason_codes

def test_conflicting_values_are_preserved() -> None:
    result = detect_conflicts([claim("探测距离", "20km", "ev-1"), claim("探测距离", "35km", "ev-2")])
    assert result[0].status == "unresolved"
    assert set(result[0].evidence_ids) == {"ev-1", "ev-2"}
```

- [ ] **Step 2: 运行并确认失败**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_evidence_filter.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现过滤管线**

流程：URL/content 去重 -> 质量评分 -> claim 直接支撑校验 -> 来源独立性聚类 -> 印证计数 -> 参数/时间/主体冲突检测 -> 反证标记 -> accepted/candidate/rejected。来源独立性按机构、转载链和内容 hash 判断，不只按域名。

- [ ] **Step 4: 运行证据测试**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_evidence_filter.py -q`

Expected: PASS。

- [ ] **Step 5: 验证高置信规则**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_evidence_filter.py -q -k corroboration`

Expected: 单源关键 claim 最高标记 medium，两个独立来源后才可 high。

### Task 5: 注册原子联网工具并接入 ResearchLoop

**Files:**
- Modify: `src/equipment_deep_research/tools/registry.py`
- Modify: `src/equipment_deep_research/orchestration/research_loop.py`
- Test: `tests/equipment_deep_research/integration/test_network_research_tools.py`

**Interfaces:**
- Produces tools: `search_sources`、`fetch_page`、`read_material`、`create_evidence_card`、`write_finding_packet`。

- [ ] **Step 1: 写失败集成测试**

```python
@pytest.mark.asyncio
async def test_search_fetch_read_evidence_chain(runtime_with_http_fixture) -> None:
    result = await runtime_with_http_fixture.execute(research_task())
    assert result.tool_sequence[:4] == [
        "search_sources", "fetch_page", "read_material", "create_evidence_card"
    ]
    evidence = result.store.get("EvidenceCard", "ev-1")
    assert evidence.artifact_refs
    assert evidence.source_location
    assert evidence.quality_score >= 0.62
```

- [ ] **Step 2: 运行并确认失败**

Run: `python3 -m pytest tests/equipment_deep_research/integration/test_network_research_tools.py -q`

Expected: FAIL。

- [ ] **Step 3: 注册最小原子工具**

`search_sources` 只返回 lead；`fetch_page` 只抓取和材料化；`read_material` 按段落或关键词读取；`create_evidence_card` 校验 location 和评分；`write_finding_packet` 只引用 accepted evidence。

- [ ] **Step 4: 运行工具链测试**

Run: `python3 -m pytest tests/equipment_deep_research/integration/test_network_research_tools.py -q`

Expected: PASS。

- [ ] **Step 5: 验证工具权限差异**

Run: `python3 -m pytest tests/equipment_deep_research/integration/test_network_research_tools.py -q -k permission`

Expected: reporter 和 auditor 无法调用 fetch；baseline agent 无法直接写 capability image。

### Task 6: 完成真实联网 smoke

**Files:**
- Modify: `src/equipment_deep_research/orchestration/runner.py`
- Create: `tests/equipment_deep_research/e2e/test_real_smoke.py`
- Create: `docs/testing/phase-7-test-report.md`
- Create: `examples/real-smoke/README.md`

**Interfaces:**
- Consumes: Responses provider、搜索 provider、原子联网工具、证据过滤。
- Produces: real smoke run 和可审计降级状态。

- [ ] **Step 1: 写离线 mock smoke 测试**

测试使用 mock Responses + HTTP fixture，断言至少一个 accepted EvidenceCard、raw/simplified artifacts、packet evidence refs、能力画像 evidence refs 和无白名单阻断状态。

- [ ] **Step 2: 运行 mock smoke**

Run: `python3 -m pytest tests/equipment_deep_research/e2e/test_real_smoke.py -q`

Expected: 初次 FAIL，接入后 PASS。

- [ ] **Step 3: 增加真实 smoke 命令和状态规则**

```bash
python3 scripts/run_deep_research.py \
  --mode real \
  --topic "低空无人机探测预警与抗干扰能力需求" \
  --research-route auto \
  --agents international_situation,combat_scenario,weapon_equipment,operational_employment \
  --run-id real-smoke-001
```

网络/凭据不可用时退出码仍为 0，但 audit 为 `limited`，summary 必须记录具体 provider/network error；没有 accepted evidence 时不得输出 approved。

- [ ] **Step 4: 运行全量自动测试**

Run: `python3 -m pytest -q`

Expected: 全部 PASS。

- [ ] **Step 5: 生成 Phase 7 审查包**

在网络和凭据可用环境执行真实 smoke；报告记录命令、run-id、搜索数量、抓取成功数、accepted/candidate/rejected 数、冲突数、artifact refs 和审计状态。若环境不可用，附降级产物并明确真实在线验收仍需在目标环境执行。
