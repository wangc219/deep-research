from hashlib import sha256
import json

from equipment_deep_research.agents.dynamic_prompt_resources import load_dynamic_winning_prompt
from equipment_deep_research.agents.runtime_profiles import (
    build_codex_runtime_profile,
    is_dynamic_winning_payload,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    S6_PORTRAIT_QUALITY_CONTRACT_VERSION,
    _compact_s6_authored_card_event,
    _dynamic_s6_card_input,
    _dynamic_s6_input_fingerprint,
    _dynamic_s6_module_guidance,
    _s6_short_portrait_modules,
    _parallel_s6_card_instruction,
)
from equipment_deep_research.agents.workflows.winning_flows.s6_authoring import (
    _clean_s6_technology_prose,
    _merge_s6_repaired_modules,
    _parallel_s6_semantic_quality_issues,
    _portrait_repair_keys,
    _s6_repair_root_fingerprints,
    _s6_repair_meets_length_contract,
)
from equipment_deep_research.orchestration.capability_portrait import (
    CAPABILITY_PORTRAIT_MODULES,
    CAPABILITY_PORTRAIT_QUALITY_CONTRACT_VERSION,
    CAPABILITY_PORTRAIT_REPAIR_TRIGGER_CHARS,
    assemble_capability_portrait_modules,
    cap_portrait_module_length,
    capability_portrait_quality_issues,
)


def test_empty_or_retrieval_only_technology_prose_does_not_become_a_template() -> None:
    brief = {
        "name": "测试装备",
        "operational_mechanism": "闭合直接作用链",
    }
    assert _clean_s6_technology_prose("", brief) == ""
    assert _clean_s6_technology_prose("本轮联网检索失败，未返回可靠公开来源。", brief) == ""


def test_portrait_repair_preserves_complete_siblings():
    modules = {key: '完整论证。' for key, _ in CAPABILITY_PORTRAIT_MODULES}
    assert _portrait_repair_keys(modules, ['概述缺少具体论证']) == ['overview']
    assert _portrait_repair_keys(modules, []) == []


def test_dynamic_s6_input_keeps_authoring_spine_and_drops_evidence_metadata():
    brief = {
        "name": "断链复核巡猎弹",
        "primary_equipment_identity": "弹载自主复核巡猎弹药",
        "equipment_form": "弹载巡猎弹",
        "target_and_direct_effect": "在断链窗口复核并压缩目标机动空间",
        "concise_winning_summary": "传统稳定链路失效后，弹上闭环恢复时敏追击窗口",
        "non_substitutable_difference": "把复核与末端动作收敛到弹体内",
        "new_operational_mode": "断链条件下自主确认并续接打击",
        "winning_relation_shift": "由平台暴露交换转为弹上闭环交换",
        "failure_boundary": "强干扰时能力下降",
        "failure_boundaries": ["目标确认不足时拒打"],
        "evidence_boundary": "公开证据不证明完整作战效能",
        "direct_evidence_refs": ["ev-secret"],
        "evidence_refs": ["ev-secret-2"],
        "evidence_ids": ["ev-secret-3"],
        "validation_plan": ["开展对照试验"],
        "indicator_portrait": "复核时延与目标机动变化",
    }

    payload = _dynamic_s6_card_input(brief, query="断链条件下的时敏追击")
    serialized = json.dumps(payload, ensure_ascii=False)

    candidate = payload["candidate_weapon"]
    assert candidate["name"] == brief["name"]
    assert candidate["primary_equipment_identity"] == brief[
        "primary_equipment_identity"
    ]
    assert candidate["overview"] == brief["concise_winning_summary"]
    assert payload["query_semantics"] == "断链条件下的时敏追击"
    for forbidden in (
        "failure_boundary",
        "failure_boundaries",
        "evidence_boundary",
        "direct_evidence_refs",
        "evidence_refs",
        "evidence_ids",
        "validation_plan",
        "indicator_portrait",
    ):
        assert forbidden not in serialized


def test_portrait_repair_scopes_missing_and_truncated_columns():
    modules = {key: '完整论证。' for key, _ in CAPABILITY_PORTRAIT_MODULES}
    modules['overview'] = ''
    modules['winning_logic'] = '其结果转化为'
    assert _portrait_repair_keys(
        modules, ['装备能力画像缺少完整五栏，无法执行精简度交付门']
    ) == ['overview', 'winning_logic']


def test_portrait_repair_keeps_global_diagnostics_in_scope():
    modules = {key: '完整论证。' for key, _ in CAPABILITY_PORTRAIT_MODULES}
    assert _portrait_repair_keys(
        modules, ['装备能力画像存在跨栏重复（2组栏目复用相同或近似长句）']
    ) == [key for key, _ in CAPABILITY_PORTRAIT_MODULES]


def test_s6_repair_root_fingerprint_rejects_same_cause_as_progress():
    before = _s6_repair_root_fingerprints(
        [
            "概述明显过短，低于约180字告警线",
            "装备能力画像存在跨栏重复（2组栏目复用相同或近似长句）",
        ]
    )
    after = _s6_repair_root_fingerprints(
        [
            "概述明显过短，低于约180字告警线",
            "装备能力画像存在跨栏重复（4组栏目复用相同或近似长句）",
        ]
    )

    assert after == before
    assert not after or len(after) >= len(before)


def test_s6_repair_root_fingerprint_accepts_cleared_root():
    before = _s6_repair_root_fingerprints(
        ["装备能力画像存在跨栏重复（2组栏目复用相同或近似长句）"]
    )
    after = _s6_repair_root_fingerprints([])

    assert before
    assert not after


def test_dynamic_quality_gate_detects_hollow_but_long_columns():
    modules = {
        key: "这是装备能力的一般性描述，内容保持完整并且长度足够。" * 30
        for key, _ in CAPABILITY_PORTRAIT_MODULES
    }

    issues = _parallel_s6_semantic_quality_issues(modules)

    assert "装备与技术实现未形成路线取舍和主攻链" in issues
    assert "关键作战流程未形成条件、动作、状态变化和转段闭环" in issues
    assert "形成能力与作战效果未区分新增任务、直接战果和敌方代价" in issues
    assert "制胜逻辑机理未闭合旧规则、交换关系、经济反制和新增代价" in issues


def test_dynamic_quality_gate_routes_short_columns_without_semantic_defects():
    modules = {
        "overview": (
            "敌方依靠持续机动保持优势，传统模式因窗口短而失效；本装备介入后改变暴露关系，"
            "在确认目标后形成直接战果，并打开过去无法执行的时敏任务空间。它把原本需要多级链路维持的"
            "追击任务压缩到一次可控接敌，使我方不必先暴露大型平台即可完成复核。敌方因此必须在机动、"
            "伪装和防护之间重新分配资源，原有依靠拖延窗口消耗我方的办法不再稳定。该变化直接影响"
            "任务编组的先后顺序和接敌距离，使装备选择从能否维持链路转向能否在断链时完成自主闭环。"
        ),
        "technology_implementation": (
            "主路径采用弹上复核方案，备选为外部节点引导；前者减少链路依赖但增加算力与散热取舍，"
            "核心瓶颈是低时延识别，需将算法写入弹上处理模块并按先感知后控制顺序攻关。主路径适合断链"
            "窗口，备选路径适合平台仍能稳定提供引导的场景；两者的取舍取决于抗干扰余量、能源和舱内空间。"
            "工程上先解决传感器与飞控接口，再验证热控和控制面联锁，避免只堆叠器件却无法形成闭环。"
            "只有处理链、导航源和控制面在同一时限内稳定协同，弹体才会把识别结果转化为可执行动作，"
            "否则备选路线应保留为受控降级，而不能把实验室精度直接等同于战场能力。"
        ),
        "operational_process": (
            "编组在授权且目标进入窗口后部署装备，先完成状态确认再释放；回传异常时拒打，"
            "确认后切换到末端动作，若目标离开窗口则终止，若窗口保持则续接后续战果。行动主体由前沿"
            "节点完成初筛，任务单元只接收已确认的交战条件；状态从待机转为搜索、复核和末端控制，"
            "任何授权撤回都触发安全脱离并释放后续编组，不把一次失败强行包装成有效战果。"
            "每次状态转移都由对应条件触发并留下可回传的确认结果，后续单元只有在前一状态完成后才接管，"
            "从而避免多个节点同时动作导致目标重新获得隐蔽窗口。"
        ),
        "capability_effects": (
            "过去部队无法在断链条件下完成连续确认，现在新增时敏追击任务；直接战果是压缩目标机动空间，"
            "并迫使敌方增加防护和成本，最终打开我方持续作战空间。新增任务不是单纯提高命中概率，而是"
            "让原本因无法复核而放弃的短窗口重新可用；直接效果表现为目标被迫减速、分散或提前暴露。"
            "后续部队据此获得再定位和连续施压的机会，敌方则需要增加诱饵、护航和指挥资源。"
            "这类效果应以任务是否能够继续、目标是否被迫改变行动和防护是否提前启动来观察，"
            "而不能仅用单项命中率上升概括；其价值在于把一次短促交战延长为可持续的选择压力。"
        ),
        "winning_logic": (
            "旧规则要求稳定链路才能交换火力，本装备逆转这一假设；交换关系由平台暴露转为弹上闭环，"
            "敌方若反制就要付出时间、兵力和防御成本，暴露增加后难以低成本恢复原有优势。对手最经济的"
            "反制是提前清理接敌窗口，但这会牺牲机动节奏并暴露编组；若转而加强防御，又要承担持续拦截"
            "和弹药消耗。因而我方获得的不是一次性突袭，而是让敌方每次恢复旧规则都付出新的交换代价。"
            "如果敌方选择分散部署，防护密度和指挥效率又会下降；如果保持集中，则更容易被连续施压。"
            "该机理成立的前提是装备仍能保持自主复核、末端控制和有限能源供给，不能脱离这些条件空谈优势。"
        ),
    }

    issues = _parallel_s6_semantic_quality_issues(modules)
    assert set(_s6_short_portrait_modules(modules)) == {
        key for key, _ in CAPABILITY_PORTRAIT_MODULES
    }
    assert len(issues) == len(CAPABILITY_PORTRAIT_MODULES)
    assert all("低于约360字软目标" in issue for issue in issues)


def test_short_column_cannot_be_hidden_by_other_long_columns():
    modules = {key: '文' * 450 for key, _ in CAPABILITY_PORTRAIT_MODULES}
    modules['overview'] = '文' * 359 + '。' * 20
    assert _s6_short_portrait_modules(modules) == ['overview']
    modules['overview'] = '文' * 360
    assert _s6_short_portrait_modules(modules) == []


def test_missing_technology_module_is_never_hidden_by_complete_siblings():
    modules = {
        key: '文' * 420
        for key, _ in CAPABILITY_PORTRAIT_MODULES
        if key != 'technology_implementation'
    }
    assert _s6_short_portrait_modules(modules) == ['technology_implementation']


def test_first_pass_prompt_uses_soft_400_target_without_upper_bound():
    for prompt in (load_dynamic_winning_prompt('S6'), _parallel_s6_card_instruction()):
        assert '约400个有效中文字' in prompt
        assert '复杂因果尚未闭合时可适当略多' in prompt
        assert '禁止按字符硬切' in prompt
        assert '有效中文字' in prompt
        assert '不能用总字数或平均数抵消短栏' in prompt
        assert '明显超过约350字' not in prompt
        assert '低于约300字' not in prompt


def test_parallel_portrait_columns_use_separate_markdown_owned_prompts():
    keys = [key for key, _ in CAPABILITY_PORTRAIT_MODULES]
    prompts = [_dynamic_s6_module_guidance(key) for key in keys]
    assert len(set(prompts)) == 5
    for prompt in prompts:
        assert "360至400个有效中文字为常规目标" in prompt
        assert "可适当略多" in prompt
        assert "禁止按字符硬切" in prompt


def test_repair_accepts_complete_columns_without_an_upper_bound():
    first_pass = {key: '原' * 420 for key, _ in CAPABILITY_PORTRAIT_MODULES}
    first_pass['overview'] = '旧' * 100
    first_pass['technology_implementation'] = '旧' * 120
    repaired = {key: '改' * 420 for key, _ in CAPABILITY_PORTRAIT_MODULES}
    repaired['technology_implementation'] = '改' * 359 + '。' * 20
    pending = ['overview', 'technology_implementation']

    candidate = _merge_s6_repaired_modules(first_pass, repaired, pending)
    assert candidate['operational_process'] == first_pass['operational_process']
    assert _s6_repair_meets_length_contract(candidate, pending)

    repaired['technology_implementation'] = ''
    candidate = _merge_s6_repaired_modules(first_pass, repaired, pending)
    assert not _s6_repair_meets_length_contract(candidate, pending)


def test_long_complete_column_is_preserved_and_incomplete_tail_is_reported():
    complete = '敌方以持续机动隐藏目标，装备在有限窗口内完成复核并形成直接毁伤，迫使其改变部署并暴露新的防护节点。' * 10
    assert len(complete) > 400
    assert cap_portrait_module_length(complete) == complete

    modules = {key: complete for key, _ in CAPABILITY_PORTRAIT_MODULES}
    modules['winning_logic'] = complete[:-1] + '转化为'
    issues = capability_portrait_quality_issues(modules)
    assert any('制胜逻辑机理句末疑似截断' in issue for issue in issues)


def test_live_card_projection_does_not_truncate_five_full_columns():
    modules = {key: '文' * 400 for key, _ in CAPABILITY_PORTRAIT_MODULES}
    portrait = assemble_capability_portrait_modules(modules)
    assert len(portrait) > 1800

    event = _compact_s6_authored_card_event({
        'name': '测试卡',
        'capability_portrait': portrait,
        'capability_portrait_modules': modules,
    })

    assert event['capability_portrait'] == portrait
    assert event['capability_portrait_modules'] == modules


def test_dynamic_s6_cache_fingerprint_includes_quality_contract_version():
    payload = {'query_semantics': '测试', 'candidate_weapon': {'name': '测试卡'}}
    legacy_serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    )
    legacy_fingerprint = sha256(legacy_serialized.encode('utf-8')).hexdigest()

    assert S6_PORTRAIT_QUALITY_CONTRACT_VERSION.startswith('s6-portrait-v5-')
    assert f'target{CAPABILITY_PORTRAIT_REPAIR_TRIGGER_CHARS}' not in (
        S6_PORTRAIT_QUALITY_CONTRACT_VERSION
    )
    assert S6_PORTRAIT_QUALITY_CONTRACT_VERSION == (
        CAPABILITY_PORTRAIT_QUALITY_CONTRACT_VERSION
    )
    assert _dynamic_s6_input_fingerprint(payload) != legacy_fingerprint
    assert _dynamic_s6_input_fingerprint(payload) == _dynamic_s6_input_fingerprint(payload)


def test_isolated_s6_payload_gets_s6_runtime_identity_without_generic_quality_card():
    payload = {
        'query_semantics': '强干扰下的时敏目标猎歼',
        'candidate_weapon': {
            'name': '断链复核巡猎弹',
            'card_binding_id': 's6-card-contract-test',
        },
        'winning_logic_overview': '把持续链路依赖改为弹上受控复核。',
    }

    assert is_dynamic_winning_payload(payload)
    assert is_dynamic_winning_payload({'input': {'input': payload}})
    runtime = build_codex_runtime_profile(
        'winning_s6_image',
        payload={'input': payload},
        phase='winning_s6_parallel_card_01',
        compact=True,
    )

    assert runtime['mission_node'] == 'S6'
    assert runtime['skill'] == '单装备能力画像编辑'
    for removed in (
        'methodology',
        'quality_gates',
        'harness',
        'research_policy',
        'output_contract',
    ):
        assert removed not in runtime


def test_s6_shape_requires_governed_card_binding_prefix():
    payload = {
        'query_semantics': '测试',
        'candidate_weapon': {'card_binding_id': 'not-an-s6-card'},
        'winning_logic_overview': '测试',
    }

    assert not is_dynamic_winning_payload(payload)
