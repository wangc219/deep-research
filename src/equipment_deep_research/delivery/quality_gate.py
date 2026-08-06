"""报告质量门控模块

基于架构设计文档的核心质量要求（深度性、军事价值性、新颖性、前瞻性与格式完整性）
自动检查报告质量。
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any
import logging

from equipment_deep_research.domain.research_focus import (
    disruptive_relationship_groups,
)

logger = logging.getLogger(__name__)


CANONICAL_REPORT_H2 = (
    "第一层：需求挖掘层——场景·战法/技术·装备能力特征",
    "第二层：技术攻关层——能力实现途径与核心技术",
    "第三层：能力图像与效能贡献层",
)

CANONICAL_REPORT_H3 = (
    "① 典型作战场景",
    "② 新战法或新概念技术及制胜机理",
    "③ 装备能力特征清单",
    "④ 能力实现途径",
    "⑤ 核心技术清单与攻关优先级",
    "⑥ 技术耦合与短板风险",
    "⑦ 装备能力图像",
    "⑧ 效能贡献评估",
    "⑨ 发展优先级与近期抓手",
)

PROJECT_ARGUMENT_REPORT_H2 = (
    "一、需求分析",
    "二、项目画像",
    "三、总体方案",
    "四、关键技术",
    "五、研制基础",
)

PROJECT_ARGUMENT_REPORT_H3 = (
    "（一）需求概述",
    "（二）国内外现状",
    "（三）建设必要性分析",
    "（一）装备图像概述",
    "（二）作战运用模式",
    "（三）体系贡献率分析",
    "（四）主要战技指标",
    "（一）总体架构",
    "（二）子系统方案",
    "（一）关键技术清单与攻关途径",
    "（一）参与单位",
    "（二）技术基础",
)

PROJECT_ARGUMENT_REPORT_H4 = (
    "1. 背景分析",
    "2. 需求阐述",
    "3. 项目画像",
    "1. 国外情况",
    "2. 国内现状（中国）",
    "3. 对比小结",
    "1. 作战使用角度",
    "2. 装备能力提升角度",
    "3. 领域占位角度",
    "4. 综合效益",
    "1. 作战运用流程",
    "2. 链路闭环分析",
)

GOVERNED_CAPABILITY_PORTRAIT_LABELS = (
    "装备与技术实现",
    "关键作战流程",
    "形成能力与作战效果",
    "制胜逻辑机理与对抗边界",
)

_INTERNAL_REWRITE_BOUNDARY = "〔改写断点：保留事实但不得照录〕"
_INTERNAL_CANDIDATE_PREFIX_RE = re.compile(
    r"(?m)(?:^|\|\s*|\*\*)[A-Ha-h]\s*[.．、:：]\s*(?=[^\s|*])"
)


_MILITARY_INFORMATION_SIGNALS = {
    "equipment": (
        "导弹", "巡飞弹", "弹药", "无人机", "无人平台", "发射车", "火箭炮",
        "拦截弹", "战斗部", "导引头", "雷达", "火控", "载荷", "效应器",
    ),
    "adversary": (
        "敌方", "对手", "目标", "威胁", "反制", "干扰", "压制", "拒止",
        "欺骗", "诱饵", "拦截", "防空", "电磁静默", "GNSS", "PNT",
    ),
    "action": (
        "部署", "待机", "进入", "搜索", "复核", "发射", "突防", "交战",
        "拒打", "拒击", "中止", "压制", "摧毁", "猎歼", "补射", "补击",
        "接替", "评估", "再组织", "射后转移", "任务装订",
    ),
    "effect": (
        "战果", "毁伤", "阻断", "续接", "恢复", "开辟", "压缩", "迫使",
        "降低", "提升", "任务成功率", "压制窗口", "火力空窗", "交换比",
        "单位有效毁伤成本", "直接效果",
    ),
    "validation": (
        "验证", "试验", "指标", "判据", "通过条件", "失败条件", "验收",
        "门槛", "待核验", "待校准", "仿真", "半实物", "硬件在环", "海试",
    ),
    "decision": (
        "P0", "P1", "P2", "优先级", "优先", "建设", "取舍", "转段",
        "停止", "终止", "降级", "近期", "中期", "远期", "成熟度",
    ),
    "evidence": (
        "公开证据", "公开资料", "来源", "事实", "推断", "假设", "基线",
        "型号", "项目", "待核验",
    ),
}

_GENERIC_MILITARY_FILLER = (
    "具有重要意义",
    "意义重大",
    "复杂多变",
    "日益严峻",
    "总体来看",
    "综合而言",
    "全面提升",
    "迫切需要",
    "奠定坚实基础",
    "提供有力支撑",
    "新质战斗力",
    "体系化、实战化和智能化",
)


def _military_information_units(report: str) -> list[str]:
    """Return prose decision units while excluding headings and Markdown tables."""

    units: list[str] = []
    paragraph: list[str] = []

    def flush() -> None:
        if not paragraph:
            return
        value = "".join(paragraph).strip()
        paragraph.clear()
        value = re.sub(r"^(?:[-*]\s+|\d+[.、]\s*)", "", value).strip()
        if len(re.sub(r"\s+", "", value)) >= 28:
            units.append(value)

    for raw_line in str(report or "").splitlines():
        line = raw_line.strip()
        if not line:
            flush()
            continue
        if line.startswith("#") or (line.startswith("|") and line.endswith("|")):
            flush()
            continue
        if re.match(r"^(?:[-*]\s+|\d+[.、]\s*)", line):
            flush()
            paragraph.append(line)
            flush()
            continue
        paragraph.append(line)
    flush()
    return units


def _military_decision_section_body(section_body: str) -> str:
    """Exclude evidence appendices embedded under a decision-oriented H2.

    The compact report intentionally appends a bold ``核心公开来源索引`` after
    the final project section instead of introducing a contract-external H2.
    Those citation catalogue entries are evidence metadata, not military
    decision prose, and therefore must not dilute the parent section's density.
    """

    marker = re.search(
        r"(?m)^\s*(?:\*\*|__)?核心公开来源索引(?:\*\*|__)?\s*$",
        str(section_body or ""),
    )
    return section_body[: marker.start()] if marker else section_body


def _military_decision_report(report: str) -> str:
    """Return only sections expected to carry military decision density.

    ``五、研制基础`` may legitimately contain participating-unit status,
    category-level technical foundations and evidence catalogues.  It remains
    subject to the report's evidence and completeness gates, but it must not
    dilute the military decision-density score when the preceding argument is
    already dense.
    """

    text = str(report or "")
    h2_matches = list(re.finditer(r"(?m)^##\s+([^#\n].*)$", text))
    if not h2_matches:
        return text
    retained: list[str] = [text[: h2_matches[0].start()]]
    for index, match in enumerate(h2_matches):
        end = h2_matches[index + 1].start() if index + 1 < len(h2_matches) else len(text)
        title = match.group(1).strip()
        if re.match(r"^(?:五[、.]|五\s|研制基础$)", title):
            continue
        retained.append(text[match.start() : end])
    return "".join(retained)


def _military_information_signal_groups(
    text: str,
    equipment_names: list[str],
) -> set[str]:
    groups = {
        group
        for group, terms in _MILITARY_INFORMATION_SIGNALS.items()
        if any(term in text for term in terms)
    }
    if any(name and name in text for name in equipment_names):
        groups.add("named_equipment")
    return groups


def _normalized_reuse_unit(text: str) -> str:
    value = re.sub(r"https?://\S+", "", str(text or ""))
    value = re.sub(r"[*_`>#\[\](){}‘’“”\"']", "", value)
    return re.sub(r"[\s，,。；;：:！？!?、|—-]+", "", value)


def _report_military_information_metrics(
    report: str,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    """Measure decision value without treating total report length as quality."""

    metadata = metadata or {}
    enabled = bool(metadata.get("require_high_value_military_information"))
    names = [
        str(item).strip()
        for item in metadata.get("expected_capability_directions", [])
        if str(item).strip()
    ]
    if not enabled:
        return {
            "enabled": False,
            "unit_count": 0,
            "decision_dense_ratio": 1.0,
            "generic_filler_ratio": 0.0,
            "repeated_long_unit_ratio": 0.0,
            "maximum_long_unit_reuse": 1,
            "equipment_bundle_coverage": 1.0,
            "missing_equipment_bundles": [],
            "section_metrics": [],
            "low_density_sections": [],
        }

    decision_report = _military_decision_report(report)
    units = _military_information_units(decision_report)
    def density_counts(section_units: list[str]) -> tuple[int, int]:
        dense_count = 0
        generic_count = 0
        for unit in section_units:
            groups = _military_information_signal_groups(unit, names)
            operational_groups = groups & {
                "adversary", "action", "effect", "validation", "decision", "evidence"
            }
            dense = (
                ("named_equipment" in groups and bool(operational_groups))
                or ("equipment" in groups and len(operational_groups) >= 2)
                or len(operational_groups) >= 3
            )
            dense_count += int(dense)
            generic_count += int(
                any(marker in unit for marker in _GENERIC_MILITARY_FILLER)
                and "named_equipment" not in groups
                and "equipment" not in groups
                and len(operational_groups) <= 2
            )
        return dense_count, generic_count

    dense_count, generic_count = density_counts(units)
    reuse_units: list[str] = []
    for unit in units:
        for sentence in re.split(r"(?<=[。！？!?；;])", unit):
            normalized = _normalized_reuse_unit(sentence)
            if len(normalized) >= 30:
                reuse_units.append(normalized)

    reuse_counts: dict[str, int] = {}
    for unit in reuse_units:
        reuse_counts[unit] = reuse_counts.get(unit, 0) + 1
    repeated_occurrences = sum(max(0, count - 1) for count in reuse_counts.values())
    maximum_reuse = max(reuse_counts.values(), default=1)

    missing_bundles: list[str] = []
    for name in names:
        windows: list[str] = []
        start = 0
        while True:
            position = report.find(name, start)
            if position < 0:
                break
            windows.append(report[max(0, position - 240) : position + len(name) + 900])
            start = position + len(name)
        groups = _military_information_signal_groups(" ".join(windows), [name])
        if not {"adversary", "action", "effect", "validation"}.issubset(groups):
            missing_bundles.append(name)

    section_metrics: list[dict[str, Any]] = []
    h2_matches = list(re.finditer(r"(?m)^##\s+([^#\n].*)$", decision_report))
    for index, match in enumerate(h2_matches):
        section_body = decision_report[
            match.end() : h2_matches[index + 1].start()
            if index + 1 < len(h2_matches)
            else len(decision_report)
        ]
        section_units = _military_information_units(
            _military_decision_section_body(section_body)
        )
        if len(section_units) < 2:
            continue
        section_dense, section_generic = density_counts(section_units)
        section_metrics.append(
            {
                "title": match.group(1).strip(),
                "unit_count": len(section_units),
                "decision_dense_ratio": section_dense / len(section_units),
                "generic_filler_ratio": section_generic / len(section_units),
            }
        )
    low_density_sections = [
        item["title"]
        for item in section_metrics
        if item["decision_dense_ratio"] < 0.50
        or item["generic_filler_ratio"] > 0.25
    ]

    unit_count = len(units)
    return {
        "enabled": True,
        "unit_count": unit_count,
        "decision_dense_ratio": dense_count / unit_count if unit_count else 0.0,
        "generic_filler_ratio": generic_count / unit_count if unit_count else 1.0,
        "repeated_long_unit_ratio": (
            repeated_occurrences / len(reuse_units) if reuse_units else 0.0
        ),
        "maximum_long_unit_reuse": maximum_reuse,
        "equipment_bundle_coverage": (
            (len(names) - len(missing_bundles)) / len(names) if names else 1.0
        ),
        "missing_equipment_bundles": missing_bundles,
        "section_metrics": section_metrics,
        "low_density_sections": low_density_sections,
    }


_SEMANTIC_CLIPPING_PATTERNS = (
    re.compile(r"(?:…|\.\.\.)"),
    re.compile(r"(?:压制关|远程精确制|现有发为对照|多供应链替代与批)(?=[\s，。；、|]|$)"),
    re.compile(r"(?:效应器及|消耗任务的|为\s*JASSM-ER|拖垮该|候选A的驻)(?=[\s，。；、|]|$)"),
    re.compile(r"(?:的任|的鉴权与)(?=[，、；。])"),
    re.compile(r"(?:接收|目录|形成|实施|继续|发生|经过授权)(?:接|目|形|实|继|发|经)(?=[；。|]|$)"),
    re.compile(r"(?:并以安全|降低攻击)(?=[。；|]|$)"),
    re.compile(r"(?:试验|验证|闭环试验)，确(?=[。；|]|$)"),
    re.compile(r"(?:导航|任务区|通过条件)推进(?=[。；|]|$)"),
    re.compile(r"(?:^|[；：])通过条件(?:为)?(?=[。；|]|$)"),
)


def _semantic_clipping_sample(text: str) -> str:
    """Return the first known clipping trace left by destructive field slicing."""

    value = str(text or "")
    for pattern in _SEMANTIC_CLIPPING_PATTERNS:
        match = pattern.search(value)
        if match:
            start = max(0, match.start() - 24)
            end = min(len(value), match.end() + 24)
            return value[start:end].replace("\n", " ").strip()
    for clause in re.split(r"[；。|]", value):
        compact = clause.strip(" *_'\"“”‘’，、：:；。")
        # “寻的” is the established guidance/seeker noun, not a dangling
        # possessive particle.  Treating every final Chinese “的” as clipping
        # falsely rejected complete equipment-research sentences such as
        # “核心技术集中在远程飞行、任务规划和移动目标寻的”。
        if compact.endswith("寻的"):
            continue
        if len(compact) >= 12 and compact.endswith(
            ("的", "与", "及", "把", "将", "该")
        ):
            return compact[-60:]
    return ""


def _has_dangling_report_fragment(report: str) -> bool:
    """Detect fragments that destructive clipping disguised with punctuation."""

    for raw_line in str(report).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("|") != line.endswith("|"):
            return True
        candidates = (
            [cell.strip() for cell in line.strip("|").split("|")]
            if line.startswith("|") and line.endswith("|")
            else [line]
        )
        for candidate in candidates:
            candidate = re.sub(r"^(?:[-*]\s+|\d+[\.、]\s*)", "", candidate)
            if _semantic_clipping_sample(candidate):
                return True
            for sentence in re.split(r"(?<=[。！？!?])", candidate):
                sentence = sentence.strip(" *_'\"“”‘’")
                if not sentence:
                    continue
                if re.fullmatch(
                    r".{1,100}的(?:概念|实现路径|耦合链条)[。.]",
                    sentence,
                ):
                    return True
                if re.match(r"^(?:若|如果|一旦|当)", sentence):
                    body = sentence.rstrip("。.!！?")
                    pieces = re.split(r"[，,；;]", body, maxsplit=1)
                    consequence = pieces[1] if len(pieces) > 1 else body[1:]
                    if not any(
                        marker in consequence
                        for marker in (
                            "则", "就", "会", "将", "应", "需", "可", "可能", "难以",
                            "无法", "导致", "造成", "触发", "退化", "失效", "下降", "上升",
                            "增加", "降低", "转为", "停止", "中止", "返航", "成立",
                        )
                    ):
                        return True
                locative_stub = bool(
                    re.fullmatch(
                        r"(?:在|于|从|对|面向|围绕|针对).{1,36}(?:中|下|上|内|方面|阶段|条件下)。",
                        sentence,
                    )
                ) and not any(
                    marker in sentence
                    for marker in (
                        "处于",
                        "进入",
                        "转变",
                        "形成",
                        "实现",
                        "完成",
                        "表现",
                        "采用",
                        "具备",
                        "面临",
                        "推动",
                        "支撑",
                        "决定",
                        "分为",
                    )
                )
                if locative_stub or re.fullmatch(
                    r"(?:核心|主要|当前|该)?(?:矛盾|关键|问题|难点|重点|风险)"
                    r"(?:在于|是|为|成立)?。|(?:作战|任务|目标)(?:上|方面|是|为)?。",
                    sentence,
                ) or re.fullmatch(
                    r".{0,36}(?:体现为|包括|主要是|分别为|在于|取决于|依赖于)。",
                    sentence,
                ):
                    return True
            if (
                len(re.findall(r"[、，；]", candidate)) >= 2
                and re.search(
                    r"(?:目标|任务|能力|指标|技术|平台|系统|链路|装备|方案|"
                    r"场景|风险|约束|条件|接口)[。；]$",
                    candidate,
                )
                and not any(
                    term in candidate
                    for term in (
                        "形成", "实现", "完成", "提升", "降低", "打击", "压制",
                        "猎歼", "承担", "支持", "支撑", "应对", "用于", "采用", "具备", "保持", "选择",
                        "识别", "发现", "确认", "记录", "拒打", "进入", "验证", "评估", "部署", "发射", "交战", "毁伤",
                        "表明", "说明", "决定", "依赖", "位于", "贡献", "对应",
                    )
                )
            ):
                return True
    return False


@dataclass
class QualityCheck:
    """质量检查结果"""
    dimension: str
    passed: bool
    score: float  # 0-1
    indicators: dict[str, bool]
    suggestions: list[str]


@dataclass
class QualityReport:
    """质量报告"""
    overall_score: float
    depth: QualityCheck
    military_value: QualityCheck
    novelty: QualityCheck
    foresight: QualityCheck
    format_integrity: QualityCheck
    fitness: dict[str, QualityCheck]
    passed: bool
    summary: str

    def compact(self) -> dict[str, Any]:
        """Return the publication-oriented gate result without verbose diagnostics."""

        blockers = [
            suggestion
            for item in (self.format_integrity, *self.fitness.values())
            if not item.passed
            for suggestion in item.suggestions
        ]
        return {
            "passed": self.passed,
            "overall_score": round(self.overall_score, 4),
            "core_gates": {
                "模板结构": self._compact_check(self.format_integrity),
                **{
                    name: self._compact_check(item)
                    for name, item in self.fitness.items()
                },
            },
            "blockers": list(dict.fromkeys(blockers))[:5],
            "diagnostics": {
                "depth": round(self.depth.score, 4),
                "military_value": round(self.military_value.score, 4),
                "novelty": round(self.novelty.score, 4),
                "foresight": round(self.foresight.score, 4),
            },
        }

    @staticmethod
    def _compact_check(item: QualityCheck) -> dict[str, Any]:
        return {
            "passed": item.passed,
            "score": round(item.score, 4),
            "failed": [
                name for name, value in item.indicators.items() if not value
            ][:6],
        }


class ReportQualityGate:
    """
    报告质量门控

    基于架构设计四维要求验证报告质量：
    1. 深度性 (Depth) - 因果机制、量化分析、底层逻辑
    2. 军事价值性 (Military Value) - 任务效能、体系韧性、建设优先级
    3. 新颖性 (Novelty) - 创新突破、跨域融合、相对基线
    4. 前瞻性 (Foresight) - 未来预测、演进路径、不确定性
    """

    def __init__(
        self,
        depth_threshold: float = 0.6,
        military_value_threshold: float = 0.6,
        novelty_threshold: float = 0.5,
        foresight_threshold: float = 0.6,
        format_integrity_threshold: float = 0.8,
    ):
        self.thresholds = {
            'depth': depth_threshold,
            'military_value': military_value_threshold,
            'novelty': novelty_threshold,
            'foresight': foresight_threshold,
            'format_integrity': format_integrity_threshold,
        }

    def validate(self, report: str, metadata: dict[str, Any] | None = None) -> QualityReport:
        """
        验证报告质量

        Args:
            report: 报告文本
            metadata: 元数据（Agent 输出、证据等）

        Returns:
            质量报告
        """
        # 四维检查
        depth = self._check_depth(report, metadata)
        military_value = self._check_military_value(report, metadata)
        novelty = self._check_novelty(report, metadata)
        foresight = self._check_foresight(report, metadata)
        format_integrity = self._check_format_integrity(report, metadata)

        # 报告门只检查交付合同，不重复评判上游专家已经评过的装备组合、创新性
        # 和军事价值。通用四维及原细项仍保留为诊断信号；质量模式额外阻断
        # 高字数套话、跨章复制和缺少装备—对抗—战果—验证闭环的正文。
        fitness = {
            "内容闭环": self._check_report_content_contract(report, metadata),
            "证据与验证边界": self._check_report_evidence_contract(report, metadata),
            "军事决策信息密度": self._check_report_information_density(report, metadata),
        }
        core_checks = [format_integrity, *fitness.values()]
        overall_score = sum(item.score for item in core_checks) / len(core_checks)
        passed = all(item.passed for item in core_checks)

        # 生成摘要
        summary = self._generate_summary(
            overall_score,
            passed,
            depth,
            military_value,
            novelty,
            foresight,
            format_integrity,
            fitness,
        )

        return QualityReport(
            overall_score=overall_score,
            depth=depth,
            military_value=military_value,
            novelty=novelty,
            foresight=foresight,
            format_integrity=format_integrity,
            fitness=fitness,
            passed=passed,
            summary=summary,
        )

    def _check_depth(self, report: str, metadata: dict | None) -> QualityCheck:
        """检查深度性"""
        domain_required = self._requires_unmanned_remote_fire_domain(metadata)
        indicators = {
            'has_causality': self._has_causality(report),
            'has_mechanism': self._has_mechanism(report),
            'has_quantification': self._has_quantification(report),
            'has_detailed_analysis': self._has_detailed_analysis(report),
            'has_evidence_support': self._has_evidence_support(report, metadata),
            'has_evidence_bounded_feasibility': (
                not domain_required
                or self._has_evidence_bounded_feasibility(report, metadata)
            ),
        }

        passed_count = sum(indicators.values())
        score = passed_count / len(indicators)
        passed = score >= self.thresholds['depth'] and indicators[
            'has_evidence_bounded_feasibility'
        ]

        suggestions = []
        if not indicators['has_causality']:
            suggestions.append("增加因果关系分析（如：因此、导致、由于）")
        if not indicators['has_mechanism']:
            suggestions.append("解释底层机制和原理")
        if not indicators['has_quantification']:
            suggestions.append("添加量化数据（百分比、倍数、区间）")
        if not indicators['has_detailed_analysis']:
            suggestions.append("增加详细分析，避免简单罗列")
        if not indicators['has_evidence_support']:
            suggestions.append("添加证据支撑和来源引用")
        if not indicators['has_evidence_bounded_feasibility']:
            suggestions.append("成熟度、实现路径、证据边界和待验证指标必须成套出现，禁止把推断写成既成能力")

        return QualityCheck(
            dimension='深度性',
            passed=passed,
            score=score,
            indicators=indicators,
            suggestions=suggestions,
        )

    def _check_military_value(self, report: str, metadata: dict | None) -> QualityCheck:
        """检查军事价值性"""
        domain_required = self._requires_unmanned_remote_fire_domain(metadata)
        indicators = {
            'has_effectiveness': self._has_effectiveness(report),
            'has_resilience': self._has_resilience(report),
            'has_priority': self._has_priority(report),
            'has_scenarios': self._has_scenarios(report),
            'has_capability_gap': self._has_capability_gap(report),
            'has_unmanned_remote_fire_domain_alignment': (
                not domain_required or self._has_unmanned_remote_fire_alignment(report)
            ),
            'has_capability_and_operational_concept': (
                not domain_required or self._has_capability_and_operational_concept(report)
            ),
            'has_three_track_winning_effect': (
                not domain_required or self._has_three_track_winning_effect(report)
            ),
        }

        passed_count = sum(indicators.values())
        score = passed_count / len(indicators)
        passed = score >= self.thresholds['military_value'] and all(
            indicators[key]
            for key in (
                'has_unmanned_remote_fire_domain_alignment',
                'has_capability_and_operational_concept',
                'has_three_track_winning_effect',
            )
        )

        suggestions = []
        if not indicators['has_effectiveness']:
            suggestions.append("明确任务效能提升（具体数值或倍数）")
        if not indicators['has_resilience']:
            suggestions.append("说明体系韧性增强（抗毁性、适应性）")
        if not indicators['has_priority']:
            suggestions.append("指出建设优先级（高/中/低及理由）")
        if not indicators['has_scenarios']:
            suggestions.append("关联具体作战应用场景")
        if not indicators['has_capability_gap']:
            suggestions.append("量化能力差距和弥补方案")
        if not indicators['has_unmanned_remote_fire_domain_alignment']:
            suggestions.append(
                "当前Query明确涉及无人远程火力打击，报告应保持该领域锚点，"
                "不能退化为通信、C2或保障研究；其他Query不得套用本要求"
            )
        if not indicators['has_capability_and_operational_concept']:
            suggestions.append("装备能力图像需同时给出具体装备能力、指标画像和作战运用概念")
        if not indicators['has_three_track_winning_effect']:
            suggestions.append("制胜效能需区分现役效能跃升、传统赛道跨代优势和新概念赛道开辟")

        return QualityCheck(
            dimension='军事价值性',
            passed=passed,
            score=score,
            indicators=indicators,
            suggestions=suggestions,
        )

    def _check_novelty(self, report: str, metadata: dict | None) -> QualityCheck:
        """检查新颖性"""
        domain_required = self._requires_unmanned_remote_fire_domain(metadata)
        disruptive_groups = disruptive_relationship_groups(report)
        diversity_required = bool(
            metadata and metadata.get("require_disruptive_lens_diversity")
        )
        indicators = {
            'has_innovation': self._has_innovation(report),
            'has_comparison': self._has_comparison(report),
            'has_breakthrough': self._has_breakthrough(report),
            'has_cross_domain': self._has_cross_domain(report),
            'has_disruptive_relationship_diversity': len(disruptive_groups) >= 3,
            'has_cross_generation_or_new_track': (
                not domain_required or self._has_cross_generation_or_new_track(report)
            ),
            'has_evidence_grounded_novelty': (
                not domain_required or self._has_evidence_grounded_novelty(report)
            ),
        }

        passed_count = sum(indicators.values())
        score = passed_count / len(indicators)
        passed = (
            score >= self.thresholds['novelty']
            and indicators['has_cross_generation_or_new_track']
            and indicators['has_evidence_grounded_novelty']
        )

        suggestions = []
        if not indicators['has_innovation']:
            suggestions.append("指出创新点和新增价值")
        if not indicators['has_comparison']:
            suggestions.append("与基线或传统方案对比")
        if not indicators['has_breakthrough']:
            suggestions.append("说明突破传统认知的地方")
        if not indicators['has_cross_domain']:
            suggestions.append("探索跨域融合的独特视角")
        if diversity_required and not indicators['has_disruptive_relationship_diversity']:
            suggestions.append(
                "低优先级增强：围绕具体装备补充Query因果相关的关系变化，避免罗列方法论维度"
            )
        if not indicators['has_cross_generation_or_new_track']:
            suggestions.append("说明传统赛道的跨代优势或新概念装备如何开辟新赛道")
        if not indicators['has_evidence_grounded_novelty']:
            suggestions.append("创新性必须说明相对基线改变的作战关系，并给出对手反适应或失效边界")

        return QualityCheck(
            dimension='新颖性',
            passed=passed,
            score=score,
            indicators=indicators,
            suggestions=suggestions,
        )

    def _check_foresight(self, report: str, metadata: dict | None) -> QualityCheck:
        """检查前瞻性"""
        domain_required = self._requires_unmanned_remote_fire_domain(metadata)
        indicators = {
            'has_future_prediction': self._has_future_prediction(report),
            'has_trend_analysis': self._has_trend_analysis(report),
            'has_trigger_conditions': self._has_trigger_conditions(report),
            'has_uncertainty': self._has_uncertainty(report),
            'has_evolution_path': self._has_evolution_path(report),
            'has_maturity_assessment': (
                not domain_required or self._has_maturity_assessment(report)
            ),
        }

        passed_count = sum(indicators.values())
        score = passed_count / len(indicators)
        passed = score >= self.thresholds['foresight'] and indicators[
            'has_maturity_assessment'
        ]

        suggestions = []
        if not indicators['has_future_prediction']:
            suggestions.append("给出未来 3-10 年预测")
        if not indicators['has_trend_analysis']:
            suggestions.append("分析发展趋势和方向")
        if not indicators['has_trigger_conditions']:
            suggestions.append("说明触发条件和时间节点")
        if not indicators['has_uncertainty']:
            suggestions.append("评估不确定性和风险")
        if not indicators['has_evolution_path']:
            suggestions.append("描述技术成熟度演进路径")
        if not indicators['has_maturity_assessment']:
            suggestions.append("逐项给出定性成熟度、工程瓶颈与验证状态；无证据时明确待验证")

        return QualityCheck(
            dimension='前瞻性',
            passed=passed,
            score=score,
            indicators=indicators,
            suggestions=suggestions,
        )

    def _check_format_integrity(
        self,
        report: str,
        metadata: dict | None,
    ) -> QualityCheck:
        """检查固定章节、标题层级、表格边界和残段。"""

        headings = [
            (len(match.group(1)), match.group(2).strip())
            for match in re.finditer(
                r"^(#{1,6})\s+(.+?)\s*$",
                report,
                flags=re.MULTILINE,
            )
        ]
        # The delivery renderer owns exactly one leading H1 report title. The
        # Reporter contract still forbids generating an H1 itself. Accept the
        # platform-owned wrapper only when the caller explicitly marks it and
        # it is the first non-empty line; any additional H1 remains a hard fail.
        delivery_owned_h1 = bool(metadata and metadata.get("delivery_owned_h1"))
        first_nonempty = next(
            (line.strip() for line in report.splitlines() if line.strip()),
            "",
        )
        contract_headings = list(headings)
        if (
            delivery_owned_h1
            and first_nonempty.startswith("# ")
            and contract_headings
            and contract_headings[0][0] == 1
        ):
            contract_headings = contract_headings[1:]
        h2 = [title for level, title in contract_headings if level == 2]
        h3 = [title for level, title in contract_headings if level == 3]
        h4 = [title for level, title in contract_headings if level == 4]
        project_mode = self._is_project_argument_mode(report, metadata)
        expected_h2 = (
            PROJECT_ARGUMENT_REPORT_H2 if project_mode else CANONICAL_REPORT_H2
        )
        expected_h3 = (
            PROJECT_ARGUMENT_REPORT_H3 if project_mode else CANONICAL_REPORT_H3
        )
        expected_h4 = PROJECT_ARGUMENT_REPORT_H4 if project_mode else ()
        canonical_present = all(title in h2 for title in expected_h2)
        canonical_order = h2 == list(expected_h2)
        canonical_items_present = all(title in h3 for title in expected_h3)
        canonical_items_order = h3 == list(expected_h3)
        canonical_subitems_present = all(title in h4 for title in expected_h4)
        canonical_subitems_order = h4 == list(expected_h4)
        exact_heading_counts = (
            len(h2) == len(expected_h2)
            and len(h3) == len(expected_h3)
            and len(h4) == len(expected_h4)
        )
        maximum_heading_depth = 4 if project_mode else 3
        heading_depth_ok = not any(
            level > maximum_heading_depth for level, _ in contract_headings
        )
        tables_ok = self._tables_are_bounded(report)
        paragraphs_ok = self._paragraphs_are_complete(report)
        expected_capability_directions = []
        if metadata:
            raw_expected = metadata.get("expected_capability_directions", [])
            if isinstance(raw_expected, list):
                expected_capability_directions = [
                    str(item).strip() for item in raw_expected
                    if str(item).strip()
                ][:7]
        table_capability_directions = self._capability_image_table_directions(
            report, metadata
        )
        exact_capability_direction_set = (
            not expected_capability_directions
            or (
                table_capability_directions == expected_capability_directions
                and len(table_capability_directions)
                == len(expected_capability_directions)
            )
        )
        no_h1 = not any(level == 1 for level, _ in contract_headings)
        no_internal_rewrite_boundary = _INTERNAL_REWRITE_BOUNDARY not in report
        no_internal_candidate_prefix = not _INTERNAL_CANDIDATE_PREFIX_RE.search(
            report
        )
        indicators = {
            'has_canonical_sections': canonical_present,
            'has_canonical_order': canonical_order,
            'has_canonical_items': canonical_items_present,
            'has_canonical_item_order': canonical_items_order,
            'has_canonical_subitems': canonical_subitems_present,
            'has_canonical_subitem_order': canonical_subitems_order,
            'has_exact_heading_counts': exact_heading_counts,
            'has_bounded_heading_depth': heading_depth_ok,
            'has_bounded_tables': tables_ok,
            'has_complete_paragraphs': paragraphs_ok,
            'has_exact_capability_direction_set': exact_capability_direction_set,
            'has_no_report_owned_h1': no_h1,
            'has_no_internal_rewrite_boundary': no_internal_rewrite_boundary,
            'has_no_internal_candidate_prefix': no_internal_candidate_prefix,
        }
        score = sum(indicators.values()) / len(indicators)
        template_ok = all(
            (
                canonical_present,
                canonical_order,
                canonical_items_present,
                canonical_items_order,
                canonical_subitems_present,
                canonical_subitems_order,
                exact_heading_counts,
            )
        )
        passed = (
            score >= self.thresholds['format_integrity']
            and template_ok
            and exact_capability_direction_set
            and paragraphs_ok
            and no_h1
            and no_internal_rewrite_boundary
            and no_internal_candidate_prefix
        )
        suggestions = []
        if project_mode:
            if not canonical_present or not canonical_order:
                suggestions.append("按需求分析、项目画像、总体方案、关键技术、研制基础五章组织")
            if not canonical_items_present or not canonical_items_order:
                suggestions.append("补齐项目论证模板规定的三级标题，保持章节内顺序")
            if not canonical_subitems_present or not canonical_subitems_order:
                suggestions.append("补齐需求概述、国内外现状、必要性和作战运用中的固定四级标题")
            if not exact_heading_counts:
                suggestions.append("只保留项目论证模板规定的五章及其三级、四级标题")
            if not heading_depth_ok:
                suggestions.append("项目论证模板标题最多使用四级，合并碎片化小节")
        else:
            if not canonical_present:
                suggestions.append("使用固定三个二级层，且不要增删或改名")
            if not canonical_order:
                suggestions.append("按需求挖掘层、技术攻关层、能力图像与效能贡献层组织章节")
            if not canonical_items_present:
                suggestions.append("补齐①至⑨九个固定三级项，且不要改名")
            if not canonical_items_order:
                suggestions.append("按①典型场景至⑨发展优先级与近期抓手的顺序组织")
            if not exact_heading_counts:
                suggestions.append("只保留三个二级层和九个三级项，不新增平行模板")
            if not heading_depth_ok:
                suggestions.append("标题最多使用三级，合并碎片化小节")
        if not tables_ok:
            suggestions.append("表格控制在6列、12行以内，拆分超长单元格")
        if not paragraphs_ok:
            suggestions.append("修复残句、未闭合Markdown和超长段落")
        if not exact_capability_direction_set:
            suggestions.append(
                "装备能力图像表只能逐项使用输入的具体武器装备方向，禁止新增装备包、保障节点或C2/网络主体"
            )
        if not no_h1:
            suggestions.append("报告正文不得自行输出一级标题，标题由交付层统一生成")
        if not no_internal_rewrite_boundary:
            suggestions.append("删除Reporter handoff专用的改写断点标记，内部提示不得进入正式报告")
        if not no_internal_candidate_prefix:
            suggestions.append("删除A.至H.候选分支前缀，正式报告只保留装备方向名称")
        return QualityCheck(
            dimension='格式完整性',
            passed=passed,
            score=score,
            indicators=indicators,
            suggestions=suggestions,
        )

    def _check_report_content_contract(
        self,
        report: str,
        metadata: dict | None,
    ) -> QualityCheck:
        """Check only whether the selected template carries the required argument."""

        project_mode = self._is_project_argument_mode(report, metadata)
        records = self._expected_capability_records(metadata)
        names = [str(item.get("name", "")).strip() for item in records]
        rows = self._capability_image_table_rows(report, metadata)
        row_names = [row[0] for row in rows if row]
        concept_index = 4 if project_mode else 3
        capability_projection_ok = (
            5 <= len(rows) <= 7
            and all(len(row) > concept_index for row in rows)
            and (not names or row_names == names)
        )
        require_detailed_portraits = bool(
            (metadata or {}).get("require_detailed_capability_portraits")
        )
        detailed_portraits_ok = (
            not require_detailed_portraits
            or self._detailed_capability_portraits_complete(report, names)
        )
        if project_mode:
            operation = self._section_body(
                report, "（二）作战运用模式", "（三）体系贡献率分析"
            )
            contribution = self._section_body(
                report, "（三）体系贡献率分析", "（四）主要战技指标"
            )
            indicators_section = self._section_body_at_level(
                report, 3, "（四）主要战技指标", "（一）总体架构"
            )
            solution = " ".join(
                (
                    self._section_body_at_level(
                        report, 2, "三、总体方案", "四、关键技术"
                    ),
                    self._section_body_at_level(
                        report, 2, "四、关键技术", "五、研制基础"
                    ),
                )
            )
        else:
            operation = " ".join(
                (
                    self._section_body(
                        report,
                        "① 典型作战场景",
                        "② 新战法或新概念技术及制胜机理",
                    ),
                    self._section_body(
                        report,
                        "② 新战法或新概念技术及制胜机理",
                        "③ 装备能力特征清单",
                    ),
                )
            )
            contribution = self._section_body(
                report, "⑧ 效能贡献评估", "⑨ 发展优先级与近期抓手"
            )
            indicators_section = " ".join(
                (
                    self._section_body(
                        report, "③ 装备能力特征清单", "④ 能力实现途径"
                    ),
                    self._section_body(
                        report, "⑦ 装备能力图像", "⑧ 效能贡献评估"
                    ),
                )
            )
            solution = " ".join(
                (
                    self._section_body(
                        report, "④ 能力实现途径", "⑤ 核心技术清单与攻关优先级"
                    ),
                    self._section_body(
                        report, "⑤ 核心技术清单与攻关优先级", "⑥ 技术耦合与短板风险"
                    ),
                    self._section_body(
                        report, "⑥ 技术耦合与短板风险", "⑦ 装备能力图像"
                    ),
                )
            )
        represented = sum(name in contribution for name in names if name)
        indicators = {
            "capability_projection_complete": capability_projection_ok,
            "detailed_capability_portraits_complete": detailed_portraits_ok,
            "operational_concept_and_process_present": sum(
                term in operation
                for term in (
                    "作战概念",
                    "作战流程",
                    "任务准备",
                    "编组",
                    "部署",
                    "发射",
                    "交战",
                    "毁伤评估",
                    "再组织",
                    "链路闭环",
                    "待机",
                    "搜索",
                    "确认",
                    "突防",
                    "压制",
                    "补击",
                    "中止",
                    "目标更新",
                )
            )
            >= 2,
            "system_contribution_present": any(
                term in contribution
                for term in (
                    "体系贡献",
                    "补链",
                    "强链",
                    "开链",
                    "决策周期",
                    "突防",
                    "毁伤",
                    "任务成功率",
                )
            )
            and (not names or represented >= max(1, len(names) - 1)),
            "core_indicators_present": any(
                term in indicators_section
                for term in (
                    "核心指标",
                    "战技指标",
                    "指标画像",
                    "射程",
                    "响应",
                    "精度",
                    "成本",
                    "规模",
                    "待验证",
                )
            ),
            "solution_and_technology_present": any(
                term in solution
                for term in (
                    "总体架构",
                    "子系统",
                    "硬件",
                    "软件",
                    "核心技术",
                    "技术途径",
                    "实现路径",
                    "导引头",
                    "导航",
                    "载荷",
                    "任务系统",
                    "传感器",
                    "火控",
                )
            ),
        }
        score = sum(indicators.values()) / len(indicators)
        passed = all(indicators.values())
        suggestions: list[str] = []
        if not indicators["capability_projection_complete"]:
            suggestions.append("能力画像表须完整投影5—7项既定装备方向，不新增或遗漏主体")
        if not indicators["detailed_capability_portraits_complete"]:
            suggestions.append(
                "逐装备能力画像须各出现一次，并完整包含概述与四个受控分点；不得只保留表格或标题"
            )
        if not indicators["operational_concept_and_process_present"]:
            suggestions.append("补齐作战概念、关键作战流程和链路闭环")
        if not indicators["system_contribution_present"]:
            suggestions.append("逐装备说明体系贡献及可校准效能方向")
        if not indicators["core_indicators_present"]:
            suggestions.append("列出核心战技指标；无证据时标注待验证，不要求虚构数值")
        if not indicators["solution_and_technology_present"]:
            suggestions.append("总体方案需落到子系统、硬件/软件和关键技术途径")
        return QualityCheck("内容闭环", passed, score, indicators, suggestions)

    def _check_report_evidence_contract(
        self,
        report: str,
        metadata: dict | None,
    ) -> QualityCheck:
        """Check evidence boundaries without duplicating the source-binding gate."""

        evidence_available = bool((metadata or {}).get("evidence_count")) or bool(
            re.search(r"https?://|\[[^\]]+\]\(https?://", report)
        )
        indicators = {
            "evidence_handoff_available": evidence_available,
            "fact_inference_boundary_present": any(
                term in report
                for term in ("事实", "推断", "假设", "公开证据", "证据不足", "待核验")
            ),
            "validation_boundary_present": any(
                term in report
                for term in ("待验证", "验证指标", "通过条件", "失败条件", "验收判据", "试验验证")
            ),
        }
        score = sum(indicators.values()) / len(indicators)
        passed = all(indicators.values())
        suggestions: list[str] = []
        if not evidence_available:
            suggestions.append("报告需接入至少一条公开证据；来源绑定率由独立引用门校验")
        if not indicators["fact_inference_boundary_present"]:
            suggestions.append("明确区分公开事实、分析推断与待核验假设")
        if not indicators["validation_boundary_present"]:
            suggestions.append("为关键指标或方案给出待验证边界和通过/失败判据")
        return QualityCheck("证据与验证边界", passed, score, indicators, suggestions)

    def _check_report_information_density(
        self,
        report: str,
        metadata: dict | None,
    ) -> QualityCheck:
        """Reject verbose but non-decisive military prose in quality profiles."""

        metrics = _report_military_information_metrics(report, metadata)
        if not metrics["enabled"]:
            return QualityCheck(
                "军事决策信息密度",
                True,
                1.0,
                {
                    "decision_dense_paragraphs": True,
                    "section_density_bounded": True,
                    "generic_filler_bounded": True,
                    "long_sentence_reuse_bounded": True,
                    "equipment_decision_bundles_complete": True,
                },
                [],
            )
        indicators = {
            "decision_dense_paragraphs": metrics["decision_dense_ratio"] >= 0.55,
            "section_density_bounded": not metrics["low_density_sections"],
            "generic_filler_bounded": metrics["generic_filler_ratio"] <= 0.25,
            "long_sentence_reuse_bounded": (
                metrics["repeated_long_unit_ratio"] <= 0.08
                and metrics["maximum_long_unit_reuse"] <= 2
            ),
            "equipment_decision_bundles_complete": not metrics[
                "missing_equipment_bundles"
            ],
        }
        score = sum(indicators.values()) / len(indicators)
        suggestions: list[str] = []
        if not indicators["decision_dense_paragraphs"]:
            suggestions.append(
                "军事决策信息密度不足：至少55%的正文段落须包含具体装备/项目事实，或同时形成对手反制、作战动作、直接战果、验证判据与建设取舍中的三类信息"
            )
        if not indicators["section_density_bounded"]:
            suggestions.append(
                "以下二级章节的军事决策信息密度低于50%或套话比例超过25%："
                + "、".join(metrics["low_density_sections"][:5])
            )
        if not indicators["generic_filler_bounded"]:
            suggestions.append("通用战略套话段比例过高，删除不改变装备选择、战法或验证决策的段落")
        if not indicators["long_sentence_reuse_bounded"]:
            suggestions.append(
                "跨章节长句复用过多：同一完整长句不得出现三次，重复长句实例占比不得超过8%"
            )
        if not indicators["equipment_decision_bundles_complete"]:
            suggestions.append(
                "以下装备未成套说明敌方目标/反制、我方作战动作、直接战果与验证判据："
                + "、".join(metrics["missing_equipment_bundles"][:5])
            )
        return QualityCheck(
            "军事决策信息密度",
            all(indicators.values()),
            score,
            indicators,
            suggestions,
        )

    def _check_domain_fitness(
        self,
        report: str,
        metadata: dict | None,
    ) -> QualityCheck:
        records = self._expected_capability_records(metadata)
        direct = [item for item in records if self._is_direct_combat_record(item)]
        support = [item for item in records if self._is_support_only_record(item)]
        unmanned = [item for item in records if self._is_unmanned_record(item)]
        missile = [item for item in records if self._is_remote_precision_record(item)]
        offensive = [item for item in records if self._is_offensive_strike_record(item)]
        topic = str((metadata or {}).get("topic", ""))
        strike_focused = any(term in topic for term in ("精确打击", "远程火力", "远打精打", "远域压制"))
        defensive_focus = any(term in topic for term in ("防空", "反无人", "拦截", "要地防护"))
        indicators = {
            "has_5_to_7_equipment_directions": 5 <= len(records) <= 7,
            "has_at_least_4_direct_combat_weapons": len(direct) >= 4,
            "has_direct_combat_weapon": bool(direct),
            "has_no_support_only_main_direction": not support,
            "has_unmanned_combat_equipment": bool(unmanned),
            "has_remote_precision_missile_equipment": bool(missile),
            "has_query_aligned_offensive_portfolio": (
                not strike_focused or defensive_focus or len(offensive) >= 4
            ),
            "report_stays_in_unmanned_remote_fire_domain": self._has_unmanned_remote_fire_alignment(report),
        }
        score = sum(indicators.values()) / len(indicators)
        required = (
            "has_direct_combat_weapon",
            "has_no_support_only_main_direction",
        )
        passed = all(indicators[key] for key in required)
        suggestions: list[str] = []
        if support:
            suggestions.append(
                "以下主体不是直接战斗武器装备，应下沉为体系依赖："
                + "、".join(str(item.get("name", "")) for item in support[:3])
            )
        if direct and len(direct) < max(1, (len(records) + 1) // 2):
            suggestions.append(
                "低优先级复核：具体打击、歼灭、杀伤或反杀伤武器尚未构成组合主体"
            )
        if strike_focused and not defensive_focus and len(offensive) < 4:
            suggestions.append(
                "低优先级复核：确认各方向是否真正回应Query的打击杀伤目标；"
                "无人、低空、远程与精确打击只作观察镜头，不按类别补齐"
            )
        return QualityCheck("领域属性符合性", passed, score, indicators, suggestions)

    def _check_capability_image_fitness(
        self,
        report: str,
        metadata: dict | None,
    ) -> QualityCheck:
        records = self._expected_capability_records(metadata)
        project_mode = self._is_project_argument_mode(report, metadata)
        rows = self._capability_image_table_rows(report, metadata)
        names = [str(item.get("name", "")).strip() for item in records]
        row_names = [row[0] for row in rows if row]
        indicator_cells = [row[2] for row in rows if len(row) >= 3]
        concept_index = 4 if project_mode else 3
        concept_cells = [
            row[concept_index] for row in rows if len(row) > concept_index
        ]
        generic_indicator_count = sum(
            cell in {
                "射程/响应时间/自主等级/成本量级/规模量级待证据校准",
                "待验证",
                "待证据校准",
            }
            or ("射程/响应时间" in cell and "待" in cell)
            for cell in indicator_cells
        )
        indicators = {
            "has_exact_equipment_direction_set": bool(names) and row_names == names,
            "has_5_to_7_rows": 5 <= len(rows) <= 7,
            "each_row_has_capability_indicator_and_employment": bool(rows)
            and all(len(row) >= 5 and all(cell.strip() for cell in row[:5]) for row in rows),
            "indicator_portraits_are_direction_specific": bool(indicator_cells)
            and generic_indicator_count <= 1
            and len(set(indicator_cells)) >= max(3, len(indicator_cells) - 1),
            "operational_employment_concepts_are_specific": bool(concept_cells)
            and all(len(cell) >= 24 for cell in concept_cells)
            and len(set(concept_cells)) >= max(3, len(concept_cells) - 1),
            "has_capability_domain_and_lineage_position": (
                (
                    any(term in report for term in ("形成能力", "主要能力", "能力画像"))
                    and any(
                        term in report
                        for term in ("装备平台", "总体方案", "子系统", "技术途径")
                    )
                )
                if project_mode
                else (
                    "能力域" in report
                    and any(
                        term in report
                        for term in ("谱系位置", "装备谱系", "相对现有装备")
                    )
                )
            ),
        }
        score = sum(indicators.values()) / len(indicators)
        passed = all(
            value
            for key, value in indicators.items()
            if key != "has_disruptive_relationship_diversity"
        )
        suggestions = []
        if not indicators["has_exact_equipment_direction_set"]:
            section_label = "装备图像概述" if project_mode else "⑦"
            suggestions.append(f"{section_label}第一列必须逐项等于能力画像中的具体装备名称，不得改成能力、网络或装备包")
        if not indicators["indicator_portraits_are_direction_specific"]:
            suggestions.append("每项装备需给出不同的射程/覆盖、响应、自主、成本、规模或生存指标方向，不能统一写待校准")
        if not indicators["operational_employment_concepts_are_specific"]:
            suggestions.append("逐项说明编组、待机、发射、突防、压制、毁伤或再打击的作战运用概念")
        return QualityCheck("装备能力图像", passed, score, indicators, suggestions)

    def _check_winning_effect_fitness(
        self,
        report: str,
        metadata: dict | None,
    ) -> QualityCheck:
        records = self._expected_capability_records(metadata)
        names = [str(item.get("name", "")).strip() for item in records]
        project_mode = self._is_project_argument_mode(report, metadata)
        section = (
            self._section_body(report, "（三）体系贡献率分析", "（四）主要战技指标")
            if project_mode
            else self._section_body(report, "⑧ 效能贡献评估", "⑨ 发展优先级与近期抓手")
        )
        represented = sum(name in section for name in names if name)
        indicators = {
            "has_three_winning_tracks": self._has_three_track_winning_effect(section),
            "covers_each_equipment_direction": not names or represented >= max(5, len(names) - 1),
            "has_chain_contribution_type": any(term in section for term in ("补链", "强链", "开链")),
            "has_quantifiable_effect_directions": sum(
                term in section
                for term in ("突防率", "交换比", "决策周期", "任务成功率", "压制窗口", "再打击")
            ) >= 3,
            "has_cross_generation_or_new_track_advantage": self._has_cross_generation_or_new_track(section),
            "has_evidence_boundary_for_effect": any(
                term in section for term in ("公开证据", "待验证", "无校准", "验证方向", "不承诺")
            ),
        }
        score = sum(indicators.values()) / len(indicators)
        passed = all(indicators.values())
        suggestions = []
        if not indicators["has_three_winning_tracks"]:
            suggestions.append("分别论证现役效能跃升、传统赛道跨代优势和新概念赛道开辟")
        if not indicators["covers_each_equipment_direction"]:
            suggestions.append(
                "体系贡献率分析必须逐项说明每种装备对杀伤链和作战体系的贡献"
                if project_mode
                else "⑧必须逐项说明每种装备对杀伤链和作战体系的贡献"
            )
        if not indicators["has_quantifiable_effect_directions"]:
            suggestions.append("至少给出三类可校准效能方向，如突防率、交换比、决策周期、压制窗口或任务成功率")
        return QualityCheck("制胜效能", passed, score, indicators, suggestions)

    def _check_innovation_fitness(
        self,
        report: str,
        metadata: dict | None,
    ) -> QualityCheck:
        records = self._expected_capability_records(metadata)
        names = [str(item.get("name", "")).strip() for item in records]
        project_mode = self._is_project_argument_mode(report, metadata)
        innovation_sections = (
            " ".join(
                (
                    self._section_body(report, "（一）装备图像概述", "（二）作战运用模式"),
                    self._section_body(report, "（三）体系贡献率分析", "（四）主要战技指标"),
                    self._section_body(report, "（三）建设必要性分析", None),
                )
            )
            if project_mode
            else " ".join(
                (
                    self._section_body(report, "② 新战法或新概念技术及制胜机理", "③ 装备能力特征清单"),
                    self._section_body(report, "⑧ 效能贡献评估", "⑨ 发展优先级与近期抓手"),
                )
            )
        )
        represented = sum(name in innovation_sections for name in names if name)
        indicators = {
            "has_relative_baseline_change": any(
                term in innovation_sections for term in ("相对现役", "相对基线", "传统", "从", "转向")
            ),
            "has_disruptive_relationship_diversity": len(disruptive_relationship_groups(innovation_sections)) >= 3,
            "has_adversary_readaptation": any(term in innovation_sections for term in ("对手反适应", "反适应", "诱饵", "针对性拦截")),
            "has_failure_boundary": any(term in innovation_sections for term in ("失效边界", "失败条件", "适用边界")),
            "innovation_reaches_equipment_directions": not names or represented >= max(4, len(names) - 2),
            "has_new_track_or_cross_generation_result": self._has_cross_generation_or_new_track(report),
        }
        score = sum(indicators.values()) / len(indicators)
        passed = all(indicators.values())
        suggestions = []
        if not indicators["has_disruptive_relationship_diversity"]:
            suggestions.append(
                "低优先级增强：自然补充与Query相关的关系跃迁并落实到具体装备，"
                "不得罗列方法论标签"
            )
        if not indicators["innovation_reaches_equipment_directions"]:
            suggestions.append("创新论证必须覆盖主要装备方向，不能只在总论中写一句颠覆性")
        if not indicators["has_adversary_readaptation"] or not indicators["has_failure_boundary"]:
            suggestions.append("逐项给出对手反适应和创新失效边界")
        return QualityCheck("创新性", passed, score, indicators, suggestions)

    def _check_feasibility_fitness(
        self,
        report: str,
        metadata: dict | None,
    ) -> QualityCheck:
        records = self._expected_capability_records(metadata)
        names = [str(item.get("name", "")).strip() for item in records]
        project_mode = self._is_project_argument_mode(report, metadata)
        section = (
            " ".join(
                (
                    self._section_body_at_level(report, 2, "三、总体方案", "四、关键技术"),
                    self._section_body_at_level(report, 2, "四、关键技术", "五、研制基础"),
                    self._section_body(report, "（二）技术基础", None),
                    self._section_body(report, "（三）建设必要性分析", None),
                )
            )
            if project_mode
            else " ".join(
                (
                    self._section_body(report, "④ 能力实现途径", "⑤ 核心技术清单与攻关优先级"),
                    self._section_body(report, "⑤ 核心技术清单与攻关优先级", "⑥ 技术耦合与短板风险"),
                    self._section_body(report, "⑥ 技术耦合与短板风险", "⑦ 装备能力图像"),
                    self._section_body(report, "⑨ 发展优先级与近期抓手", None),
                )
            )
        )
        represented = sum(name in section for name in names if name)
        technical_terms = {
            term
            for term in (
                "制导律", "惯导", "景象匹配", "导引头", "抗欺骗", "目标识别", "任务自主",
                "蜂群协同", "推进", "能源", "战斗部", "材料体系", "热管理", "低成本制造",
                "频谱感知", "被动测向", "数字孪生", "开放架构", "毁伤评估",
                # Equivalent engineering terminology commonly used by the
                # Reporter and public sources. These are concrete technical
                # points, not generic capability labels, and should not be
                # rejected merely because they differ from the example words.
                "多源PNT", "末段复核", "拒打逻辑", "预装订任务包", "断链降级",
                "低带宽协同", "角色重分配", "被动侦收", "关机续踪", "多谱段复核",
                "任务规划", "半实物闭环", "低空隐身", "模块载荷接口", "分布式发射",
                "组合导航", "抗GNSS", "欺骗隔离", "任务更新", "保守自治",
                "辐射活动记忆", "候选区管理", "末端识别", "拒击算法",
                "固定构型", "制造工艺", "多弹并发", "任务分配",
                "安全中止", "审计记录", "载荷接口",
            )
            if term in section
        }
        indicators = {
            "covers_each_equipment_direction": not names or represented >= max(5, len(names) - 1),
            "has_specific_core_technologies": len(technical_terms) >= 4,
            "has_maturity_per_direction": sum(term in section for term in ("成熟度", "TRL", "样机", "工程化", "现役改装")) >= 2,
            "has_bottleneck_and_priority": any(term in section for term in ("瓶颈", "卡脖子", "短板"))
            and any(term in section for term in ("P0", "P1", "P2", "优先级")),
            "has_evidence_boundary": any(term in section for term in ("公开证据", "证据不足", "待验证", "事实", "推断", "假设")),
            "has_validation_and_failure_conditions": any(
                term in section
                for term in (
                    "试验验证", "演示验证", "半实物", "实弹验证",
                    "演示项目", "综合靶场", "靶场试验", "红队试验", "联测",
                )
            )
            and any(term in section for term in ("通过条件", "失败条件", "验收指标", "判据")),
            "has_coupling_single_point_risk": any(term in section for term in ("耦合", "依赖", "级联"))
            and any(term in section for term in ("拖垮", "卡脖子", "单点", "短板")),
        }
        score = sum(indicators.values()) / len(indicators)
        passed = all(indicators.values())
        suggestions = []
        if not indicators["has_specific_core_technologies"]:
            suggestions.append("核心技术需精确到制导律、导引头、材料体系、推进能源、被动测向或协同算法等技术点")
        if not indicators["covers_each_equipment_direction"]:
            suggestions.append(
                "总体方案、关键技术和技术基础需逐项覆盖主要装备方向，不得只给通用技术模板"
                if project_mode
                else "④—⑥和⑨需逐项覆盖主要装备方向，不得只给通用技术模板"
            )
        if not indicators["has_evidence_boundary"]:
            suggestions.append("成熟度结论必须标注公开证据、推断和待验证边界，禁止把概念写成既成能力")
        if not indicators["has_validation_and_failure_conditions"]:
            suggestions.append("近期抓手需同时给出演示/靶场/半实物等验证方式，以及通过条件、失败条件或验收判据")
        return QualityCheck("可实现性（成熟度）", passed, score, indicators, suggestions)

    @staticmethod
    def _is_project_argument_mode(
        report: str,
        metadata: dict | None = None,
    ) -> bool:
        configured = str((metadata or {}).get("report_template_mode", "")).strip()
        if configured:
            return configured == "project_argument_v1"
        return bool(re.search(r"^##\s*一、需求分析\s*$", report, flags=re.MULTILINE))

    @staticmethod
    def _capability_image_table_directions(
        report: str,
        metadata: dict | None = None,
    ) -> list[str]:
        return [
            row[0]
            for row in ReportQualityGate._capability_image_table_rows(report, metadata)
        ]

    @staticmethod
    def _capability_image_table_rows(
        report: str,
        metadata: dict | None = None,
    ) -> list[list[str]]:
        project_mode = ReportQualityGate._is_project_argument_mode(report, metadata)
        start_heading = "（一）装备图像概述" if project_mode else "⑦ 装备能力图像"
        end_heading = "（二）作战运用模式" if project_mode else "⑧ 效能贡献评估"
        match = re.search(
            rf"^###\s*{re.escape(start_heading)}\s*$\n(?P<body>.*?)(?=^###\s*{re.escape(end_heading)}\s*$)",
            report,
            flags=re.MULTILINE | re.DOTALL,
        )
        body = match.group("body") if match else ""
        rows: list[list[str]] = []
        for raw_line in body.splitlines():
            line = raw_line.strip()
            if not (line.startswith("|") and line.endswith("|")):
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if not cells:
                continue
            first = cells[0]
            if first.casefold() in {
                "装备系统方向",
                "装备方向",
                "具体装备方向",
                "direction",
                "equipment direction",
                "weapon direction",
                "装备系统方向",
            }:
                continue
            if re.fullmatch(r":?-{3,}:?", first):
                continue
            if first:
                rows.append(cells)
        return rows

    @staticmethod
    def _section_body(
        report: str,
        heading: str,
        next_heading: str | None,
    ) -> str:
        end = (
            rf"(?=^###\s*{re.escape(next_heading)}\s*$)"
            if next_heading
            else r"\Z"
        )
        match = re.search(
            rf"^###\s*{re.escape(heading)}\s*$\n(?P<body>.*?){end}",
            report,
            flags=re.MULTILINE | re.DOTALL,
        )
        return match.group("body").strip() if match else ""

    @staticmethod
    def _section_body_at_level(
        report: str,
        level: int,
        heading: str,
        next_heading: str | None,
    ) -> str:
        marker = "#" * max(1, min(6, int(level)))
        end = (
            rf"(?=^{re.escape(marker)}\s*{re.escape(next_heading)}\s*$)"
            if next_heading
            else r"\Z"
        )
        match = re.search(
            rf"^{re.escape(marker)}\s*{re.escape(heading)}\s*$\n(?P<body>.*?){end}",
            report,
            flags=re.MULTILINE | re.DOTALL,
        )
        return match.group("body").strip() if match else ""

    @staticmethod
    def _expected_capability_records(metadata: dict | None) -> list[dict[str, Any]]:
        if not metadata:
            return []
        records = metadata.get("expected_capability_records", [])
        if isinstance(records, list) and records:
            return [dict(item) for item in records if isinstance(item, dict)][:7]
        return [
            {"name": str(item)}
            for item in metadata.get("expected_capability_directions", [])
            if str(item).strip()
        ][:7]

    @staticmethod
    def _detailed_capability_portraits_complete(
        report: str,
        expected_names: list[str],
    ) -> bool:
        """Require one full governed portrait for every selected direction."""

        names = [str(name).strip() for name in expected_names if str(name).strip()]
        if not names:
            return False
        title_pattern = re.compile(
            r"^\s*\*\*(?P<name>.+?)｜装备能力画像\*\*\s*$",
            flags=re.MULTILINE,
        )
        matches = list(title_pattern.finditer(report))
        if [match.group("name").strip() for match in matches] != names:
            return False
        for index, match in enumerate(matches):
            block_end = (
                matches[index + 1].start()
                if index + 1 < len(matches)
                else len(report)
            )
            block = report[match.end():block_end]
            next_heading = re.search(r"^#{1,6}\s+", block, flags=re.MULTILINE)
            if next_heading:
                block = block[:next_heading.start()]
            block = block.strip()
            if not re.search(r"^\s*概述[：:]", block, flags=re.MULTILINE):
                return False
            overview_match = re.search(
                r"^\s*概述[：:]\s*(?P<body>[^\n]+)",
                block,
                flags=re.MULTILINE,
            )
            if overview_match is None:
                return False
            overview = overview_match.group("body").strip()
            if not any(
                term in overview
                for term in (
                    "导弹",
                    "巡航弹",
                    "巡飞弹",
            "弹药",
            "无人机",
            "无人携弹平台",
            "无人艇",
                    "无人潜航器",
                    "鱼雷",
                    "拦截弹",
                    "火炮",
                    "发射车",
                    "反舰车",
                    "效应器",
                    "火控系统",
                    "电子战系统",
                    "雷达",
                )
            ):
                return False
            if not any(marker in overview for marker in ("为主装备", "为主体")):
                return False
            if not all(
                re.search(
                    rf"^\s*[-*]\s*{re.escape(label)}[：:]",
                    block,
                    flags=re.MULTILINE,
                )
                for label in GOVERNED_CAPABILITY_PORTRAIT_LABELS
            ):
                return False
            if not all(
                re.search(rf"(?<!\d){step}[.．、)]", block)
                for step in range(1, 5)
            ):
                return False
            if not re.search(r"型号落点|主装备对象|装备形态", block):
                return False
            if not re.search(r"以[^。；\n]{8,160}(?:验收|考核|测量|比较)", block):
                return False
            if not any(
                marker in block
                for marker in ("拒打", "降级", "中止", "失效边界")
            ):
                return False
        return True

    @staticmethod
    def _record_text(record: dict[str, Any]) -> str:
        return " ".join(
            str(record.get(key, ""))
            for key in (
                "name", "equipment_form", "equipment_category", "mission_effect",
                "military_utility", "operational_mechanism", "strike_countermeasure_value",
            )
        )

    @classmethod
    def _is_direct_combat_record(cls, record: dict[str, Any]) -> bool:
        text = cls._record_text(record)
        has_object = any(
            term in text
            for term in (
                "无人机", "无人艇", "无人潜航器", "无人僚机", "巡飞弹", "导弹", "弹药",
                "拦截弹", "火箭弹", "鱼雷", "火炮", "战斗部", "激光武器", "高功率微波",
                "电子压制器", "电子攻击效应器", "诱饵/电子攻击效应器", "武器站", "发射单元",
                "战斗机", "轰炸机",
            )
        )
        has_effect = any(
            term in text
            for term in ("打击", "猎歼", "歼灭", "杀伤", "毁伤", "再打击", "突防", "拦截", "压制", "反制", "拒止")
        )
        return has_object and has_effect and not cls._is_support_only_record(record)

    @classmethod
    def _is_support_only_record(cls, record: dict[str, Any]) -> bool:
        name = str(record.get("name", ""))
        text = cls._record_text(record)
        support_name = any(
            term in name
            for term in ("通信", "链路", "数据链", "网关", "接口", "保障", "补给", "维修", "恢复", "指挥/火控", "目标指示", "协同能力", "装备包")
        )
        direct_object_in_name = any(
            term in name
            for term in ("无人机", "无人艇", "巡飞弹", "导弹", "弹药", "拦截弹", "火箭弹", "鱼雷", "火炮", "激光武器", "高功率微波", "武器系统")
        )
        strong_effect_in_name = any(
            term in name
            for term in ("打击", "猎歼", "歼灭", "毁伤", "突防", "压制", "拦截", "反制", "拒止")
        )
        return support_name and not (direct_object_in_name and strong_effect_in_name) and not (
            any(term in text for term in ("导弹", "巡飞弹", "精确制导弹药"))
            and strong_effect_in_name
        )

    @classmethod
    def _is_unmanned_record(cls, record: dict[str, Any]) -> bool:
        text = cls._record_text(record)
        return any(
            term in text
            for term in (
                "无人机",
                "无人平台",
                "无人作战平台",
                "无人携弹平台",
                "无人火力平台",
                "无人艇",
                "无人潜航器",
                "无人僚机",
                "无人集群",
                "蜂群",
                "巡飞弹",
            )
        ) or bool(
            re.search(
                r"无人[^，；。\n]{0,18}(?:平台|飞行器|系统|装备)",
                text,
            )
        )

    @classmethod
    def _is_remote_precision_record(cls, record: dict[str, Any]) -> bool:
        text = cls._record_text(record)
        return any(term in text for term in ("导弹", "精确制导弹药", "巡航导弹", "反辐射")) and any(
            term in text for term in ("远程", "远域", "防区外", "精确", "战役纵深", "突防")
        )

    @classmethod
    def _is_offensive_strike_record(cls, record: dict[str, Any]) -> bool:
        text = cls._record_text(record)
        offensive = any(term in text for term in ("打击", "猎歼", "歼灭", "毁伤", "突防", "压制", "反辐射", "对陆", "反舰", "远域"))
        defensive_only = any(term in text for term in ("反无人", "要地防护", "低空防御")) and not any(
            term in text for term in ("远程打击", "远域压制", "对陆", "反舰", "突防")
        )
        return offensive and not defensive_only and cls._is_direct_combat_record(record)

    @staticmethod
    def _tables_are_bounded(report: str) -> bool:
        current: list[str] = []
        tables: list[list[str]] = []
        for raw in report.splitlines():
            line = raw.strip()
            if line.startswith('|') != line.endswith('|'):
                return False
            if line.startswith('|') and line.endswith('|'):
                current.append(line)
            elif current:
                tables.append(current)
                current = []
        if current:
            tables.append(current)
        for table in tables:
            widths = [len(row.strip('|').split('|')) for row in table]
            if not widths or len(set(widths)) > 1 or max(widths) > 6:
                return False
            if max(0, len(table) - 2) > 12:
                return False
            if any(
                len(cell.strip()) > 220
                for row in table
                for cell in row.strip('|').split('|')
            ):
                return False
        return True

    @staticmethod
    def _paragraphs_are_complete(report: str) -> bool:
        without_fences = re.sub(r"```.*?```", "", report, flags=re.DOTALL)
        if _has_dangling_report_fragment(without_fences):
            return False
        if re.sub(r"\\\*", "", without_fences).count("**") % 2:
            return False
        if re.sub(r"\\`", "", without_fences).count("`") % 2:
            return False
        for block in re.split(r"\n\s*\n", report.strip()):
            row = " ".join(block.split()).strip()
            if not row or row.startswith(('#', '|', '- ', '* ')):
                continue
            if len(row) > 1100:
                return False
            if row[-1] in "，、（([【“‘：" or row.endswith(
                ("包括", "如下", "例如", "即", "以及", "并且", "从而")
            ):
                return False
        return True

    # ========== 深度性指标 ==========

    def _has_causality(self, report: str) -> bool:
        """是否有因果分析"""
        patterns = [
            r'因此',
            r'导致',
            r'由于',
            r'原因.*是',
            r'结果.*是',
            r'使得',
            r'从而',
        ]
        return any(re.search(p, report) for p in patterns)

    def _has_mechanism(self, report: str) -> bool:
        """是否有机制分析"""
        patterns = [
            r'机制',
            r'原理',
            r'逻辑',
            r'本质',
            r'根源',
            r'深层',
        ]
        return any(re.search(p, report) for p in patterns)

    def _has_quantification(self, report: str) -> bool:
        """是否有量化分析"""
        patterns = [
            r'\d+%',
            r'\d+倍',
            r'\d+\s*[-~至到]\s*\d+',  # 区间
            r'提升.*\d+',
            r'增加.*\d+',
            r'降低.*\d+',
        ]
        return any(re.search(p, report) for p in patterns)

    def _has_detailed_analysis(self, report: str) -> bool:
        """是否有详细分析"""
        # 检查段落长度和分析性词汇
        paragraphs = [p.strip() for p in report.split('\n\n') if p.strip()]
        long_paragraphs = [p for p in paragraphs if len(p) > 200]

        if len(long_paragraphs) < 3:
            return False

        analysis_words = ['分析', '评估', '研判', '解读', '阐述', '揭示']
        return any(word in report for word in analysis_words)

    def _has_evidence_support(self, report: str, metadata: dict | None) -> bool:
        """是否有证据支撑"""
        # 检查证据引用
        has_url = bool(re.search(r'https?://\S+', report))
        has_source = bool(
            re.search(
                r'来源[：:]|出处[：:]|依据[：:]|证据(?:与推理)?链[：:]|证据基础[：:]|ev-[\w-]+',
                report,
            )
        )

        # 检查 metadata 中的证据
        has_metadata_evidence = False
        if metadata and 'evidence_count' in metadata:
            has_metadata_evidence = metadata['evidence_count'] > 0

        return has_url or has_source or has_metadata_evidence

    # ========== 军事价值性指标 ==========

    def _has_effectiveness(self, report: str) -> bool:
        """是否有效能分析"""
        patterns = [
            r'效能',
            r'战斗力',
            r'作战能力',
            r'打击.*能力',
            r'防御.*能力',
            r'任务.*完成',
        ]
        return any(re.search(p, report) for p in patterns)

    def _has_resilience(self, report: str) -> bool:
        """是否有韧性分析"""
        patterns = [
            r'韧性',
            r'抗毁[性]?',
            r'适应[性]?',
            r'生存[性力]',
            r'容错',
            r'冗余',
        ]
        return any(re.search(p, report) for p in patterns)

    def _has_priority(self, report: str) -> bool:
        """是否有优先级"""
        patterns = [
            r'优先级[：:]?\s*(高|中|低)',
            r'(高|中|低)\s*优先',
            r'(?<![A-Za-z0-9])P[0-3](?:级|\b)',
            r'建设.*优先',
            r'紧急[性程度]',
        ]
        return any(re.search(p, report) for p in patterns)

    def _has_scenarios(self, report: str) -> bool:
        """是否有应用场景"""
        patterns = [
            r'场景[：:]',
            r'作战.*运用',
            r'战术.*应用',
            r'战役.*应用',
            r'典型.*场景',
            r'适用.*场景',
            r'级联.*场景',
            r'场景\d+',
            r'场景预测',
        ]
        return any(re.search(p, report) for p in patterns)

    def _has_capability_gap(self, report: str) -> bool:
        """是否有能力差距"""
        patterns = [
            r'差距',
            r'不足',
            r'短板',
            r'弱项',
            r'缺失',
            r'需.*弥补',
        ]
        return any(re.search(p, report) for p in patterns)

    # ========== 新颖性指标 ==========

    def _has_innovation(self, report: str) -> bool:
        """是否有创新点"""
        patterns = [
            r'创新',
            r'首次',
            r'新.*突破',
            r'独特',
            r'开创[性]?',
            r'新颖[性]?',
            r'新增机制',
            r'新能力',
            r'新研',
        ]
        return any(re.search(p, report) for p in patterns)

    def _has_comparison(self, report: str) -> bool:
        """是否有对比"""
        patterns = [
            r'相比',
            r'相较',
            r'对比',
            r'超越',
            r'优于',
            r'传统.*方式',
            r'不是.*而是',
            r'从.*转向',
            r'相对.*基线',
        ]
        return any(re.search(p, report) for p in patterns)

    def _has_breakthrough(self, report: str) -> bool:
        """是否有突破点"""
        patterns = [
            r'突破',
            r'颠覆',
            r'改变.*认知',
            r'打破.*限制',
            r'从.*转向',
            r'不再.*而是',
            r'重构',
            r'新增机制',
        ]
        return any(re.search(p, report) for p in patterns)

    def _has_cross_domain(self, report: str) -> bool:
        """是否有跨域融合"""
        patterns = [
            r'跨域',
            r'融合',
            r'协同',
            r'体系化',
            r'一体化',
            r'多域',
        ]
        return any(re.search(p, report) for p in patterns)

    # ========== 前瞻性指标 ==========

    def _has_future_prediction(self, report: str) -> bool:
        """是否有未来预测"""
        patterns = [
            r'202[6-9]|203\d',  # 2026-2039
            r'未来.*年',
            r'\d+年.*内',
            r'预计.*202\d',
            r'预测',
        ]
        return any(re.search(p, report) for p in patterns)

    def _has_trend_analysis(self, report: str) -> bool:
        """是否有趋势分析"""
        patterns = [
            r'趋势',
            r'方向',
            r'演进',
            r'发展.*路径',
            r'变化.*态势',
        ]
        return any(re.search(p, report) for p in patterns)

    def _has_trigger_conditions(self, report: str) -> bool:
        """是否有触发条件"""
        patterns = [
            r'触发.*条件',
            r'触发.*信号',
            r'前提.*条件',
            r'当.*时',
            r'如果.*则',
            r'若.+?(?:则|应|需|可|将)',
            r'一旦.+?(?:则|会|将)',
            r'失效边界',
            r'条件.*成熟',
        ]
        return any(re.search(p, report, flags=re.DOTALL) for p in patterns)

    def _has_uncertainty(self, report: str) -> bool:
        """是否有不确定性分析"""
        patterns = [
            r'不确定[性]?',
            r'风险',
            r'挑战',
            r'可能.*失败',
            r'局限[性]?',
            r'置信度',
            r'失效边界',
            r'约束',
            r'负担',
        ]
        return any(re.search(p, report) for p in patterns)

    def _has_evolution_path(self, report: str) -> bool:
        """是否有演进路径"""
        patterns = [
            r'演进.*路径',
            r'发展.*阶段',
            r'成熟度',
            r'技术.*路线',
            r'实现.*步骤',
            r'近期.+?中期.+?远期',
            r'建设.*时序',
            r'预研',
        ]
        return any(re.search(p, report, flags=re.DOTALL) for p in patterns)

    @staticmethod
    def _requires_unmanned_remote_fire_domain(metadata: dict | None) -> bool:
        if not metadata:
            return False
        context = " ".join(
            [
                str(metadata.get("topic", "")),
                str(metadata.get("supplemental_information", "")),
                " ".join(
                    str(item)
                    for item in metadata.get("expected_capability_directions", [])
                ),
            ]
        )
        unmanned = any(term in context for term in ("无人", "巡飞弹", "蜂群", "无人僚机"))
        remote_fire = any(
            term in context
            for term in ("远程", "远域", "防区外", "精确打击", "精确制导", "火力")
        )
        return unmanned and remote_fire

    @staticmethod
    def _has_unmanned_remote_fire_alignment(report: str) -> bool:
        return (
            any(term in report for term in ("无人机", "无人平台", "巡飞弹", "无人僚机", "无人集群"))
            and any(term in report for term in ("远程", "远域", "防区外", "战役纵深"))
            and any(term in report for term in ("精确打击", "精确制导", "毁伤", "压制", "歼灭", "拒止"))
        )

    @staticmethod
    def _has_capability_and_operational_concept(report: str) -> bool:
        project_mode = ReportQualityGate._is_project_argument_mode(report)
        start_heading = "（一）装备图像概述" if project_mode else "⑦ 装备能力图像"
        end_heading = "（二）作战运用模式" if project_mode else "⑧ 效能贡献评估"
        section = re.search(
            rf"^###\s*{re.escape(start_heading)}\s*$\n(?P<body>.*?)(?=^###\s*{re.escape(end_heading)}\s*$)",
            report,
            flags=re.MULTILINE | re.DOTALL,
        )
        body = section.group("body") if section else ""
        directions = ReportQualityGate._capability_image_table_directions(report)
        capability_signal = (
            any(term in body for term in ("形成能力", "主要能力", "能力画像"))
            if project_mode
            else (
                "能力域" in body
                and any(term in body for term in ("指标画像", "指标特征", "指标谱"))
            )
        )
        return 5 <= len(directions) <= 7 and capability_signal and sum(
            term in body
            for term in (
                "作战运用",
                "作战概念",
                "运用概念",
                "编组",
                "波次",
                "待机",
                "发射",
                "突防",
                "交战",
                "巡飞",
            )
        ) >= 2

    @staticmethod
    def _has_three_track_winning_effect(report: str) -> bool:
        legacy_uplift = any(
            term in report for term in ("效能跃升", "战力跃升", "作战效能跃升")
        )
        cross_generation = any(
            term in report for term in ("跨代优势", "跨代能力", "代际优势")
        )
        new_track = any(
            term in report for term in ("开辟新赛道", "新概念赛道", "形成新赛道")
        ) or (
            "开链" in report
            and any(
                term in report
                for term in ("无人", "低成本", "新质", "此前不存在", "重构")
            )
        )
        return legacy_uplift and cross_generation and new_track

    @staticmethod
    def _has_cross_generation_or_new_track(report: str) -> bool:
        return any(
            term in report
            for term in ("跨代优势", "跨代能力", "代际优势", "开辟新赛道", "新概念赛道")
        )

    def _has_evidence_grounded_novelty(self, report: str) -> bool:
        has_baseline_relation = self._has_comparison(report) or any(
            term in report
            for term in (
                "相对基线",
                "现役基线",
                "传统赛道",
                "传统关系",
                "平台绑定",
                "传感器—射手",
                "传感器-射手",
            )
        )
        has_relationship_change = self._has_breakthrough(report) or any(
            term in report for term in ("改变", "解耦", "反转", "前移", "下放")
        )
        return (
            self._has_innovation(report)
            and has_baseline_relation
            and has_relationship_change
            and bool(disruptive_relationship_groups(report))
            and any(
                term in report
                for term in ("对手反适应", "反适应", "失效边界", "失败条件", "适用边界")
            )
        )

    def _has_evidence_bounded_feasibility(
        self,
        report: str,
        metadata: dict | None,
    ) -> bool:
        return (
            self._has_evidence_support(report, metadata)
            and self._has_maturity_assessment(report)
            and any(term in report for term in ("证据不足", "公开证据", "待验证", "事实", "推断", "假设"))
            and any(term in report for term in ("试验验证", "演示验证", "验证指标", "通过条件", "失败条件"))
        )

    @staticmethod
    def _has_maturity_assessment(report: str) -> bool:
        return (
            any(term in report for term in ("成熟度", "TRL", "工程化", "样机", "现役改装"))
            and any(term in report for term in ("瓶颈", "短板", "工程风险", "集成风险"))
            and any(term in report for term in ("待验证", "试验验证", "演示验证", "实弹验证"))
        )

    # ========== 工具方法 ==========

    def _generate_summary(
        self,
        overall_score: float,
        passed: bool,
        depth: QualityCheck,
        military_value: QualityCheck,
        novelty: QualityCheck,
        foresight: QualityCheck,
        format_integrity: QualityCheck,
        fitness: dict[str, QualityCheck],
    ) -> str:
        """生成精简的发布门摘要；通用四维只保留分数诊断。"""
        lines = [
            f"质量门控: {'通过' if passed else '未通过'}；核心得分 {overall_score:.1%}",
            f"模板结构: {'通过' if format_integrity.passed else '未通过'}",
            *(
                f"{name}: {'通过' if item.passed else '未通过'}"
                for name, item in fitness.items()
            ),
            (
                "诊断分数: "
                f"深度{depth.score:.0%} / 军事价值{military_value.score:.0%} / "
                f"创新{novelty.score:.0%} / 前瞻{foresight.score:.0%}"
            ),
        ]

        # 添加改进建议
        all_suggestions = (
            [suggestion for item in fitness.values() for suggestion in item.suggestions] +
            format_integrity.suggestions
        )

        if all_suggestions:
            lines.append("阻断项: " + "；".join(dict.fromkeys(all_suggestions[:3])))

        return '\n'.join(lines)


__all__ = ['ReportQualityGate', 'QualityReport', 'QualityCheck']
