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

        fitness = {
            "领域属性符合性": self._check_domain_fitness(report, metadata),
            "装备能力图像": self._check_capability_image_fitness(report, metadata),
            "制胜效能": self._check_winning_effect_fitness(report, metadata),
            "创新性": self._check_innovation_fitness(report, metadata),
            "可实现性（成熟度）": self._check_feasibility_fitness(report, metadata),
        }

        # 用户定义的五项装备研究判据是主评分；通用深度/前瞻/格式作为
        # 诊断和发布约束保留，不能再用关键词平均分掩盖装备方向不合格。
        overall_score = sum(item.score for item in fitness.values()) / len(fitness)
        passed = all(item.passed for item in fitness.values()) and format_integrity.passed

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
            suggestions.append("报告必须持续符合无人远程火力打击装备领域，不能退化为通信、C2或保障研究")
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
            and (
                not diversity_required
                or indicators['has_disruptive_relationship_diversity']
            )
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
                "围绕具体装备自然论证至少3类不同关系变化，避免罗列方法论维度"
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
        canonical_present = all(title in h2 for title in CANONICAL_REPORT_H2)
        positions = [h2.index(title) for title in CANONICAL_REPORT_H2 if title in h2]
        canonical_order = canonical_present and positions == sorted(positions)
        canonical_items_present = all(title in h3 for title in CANONICAL_REPORT_H3)
        item_positions = [
            h3.index(title) for title in CANONICAL_REPORT_H3 if title in h3
        ]
        canonical_items_order = (
            canonical_items_present and item_positions == sorted(item_positions)
        )
        exact_heading_counts = (
            len(h2) == len(CANONICAL_REPORT_H2)
            and len(h3) == len(CANONICAL_REPORT_H3)
        )
        heading_depth_ok = not any(level > 3 for level, _ in contract_headings)
        tables_ok = self._tables_are_bounded(report)
        paragraphs_ok = self._paragraphs_are_complete(report)
        hard_max_chars = 0
        if metadata:
            try:
                hard_max_chars = int(metadata.get("report_hard_max_chars", 0) or 0)
            except (TypeError, ValueError):
                hard_max_chars = 0
        report_length_ok = hard_max_chars <= 0 or len(report.strip()) <= hard_max_chars
        expected_capability_directions = []
        if metadata:
            raw_expected = metadata.get("expected_capability_directions", [])
            if isinstance(raw_expected, list):
                expected_capability_directions = [
                    str(item).strip() for item in raw_expected
                    if str(item).strip()
                ][:7]
        table_capability_directions = self._capability_image_table_directions(
            report
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
        indicators = {
            'has_canonical_sections': canonical_present,
            'has_canonical_order': canonical_order,
            'has_canonical_items': canonical_items_present,
            'has_canonical_item_order': canonical_items_order,
            'has_exact_heading_counts': exact_heading_counts,
            'has_bounded_heading_depth': heading_depth_ok,
            'has_bounded_tables': tables_ok,
            'has_complete_paragraphs': paragraphs_ok,
            'has_bounded_report_length': report_length_ok,
            'has_exact_capability_direction_set': exact_capability_direction_set,
            'has_no_report_owned_h1': no_h1,
        }
        # Keep the length signal observable without lowering the gating score.
        # It is an editorial preference and must not turn an otherwise valid
        # report into `limited` or cause another Reporter call.
        scored_indicators = {
            key: value
            for key, value in indicators.items()
            if key != 'has_bounded_report_length'
        }
        score = sum(scored_indicators.values()) / len(scored_indicators)
        # Length remains visible as a diagnostic indicator, but it is not a
        # delivery hard-stop. Substantive reports over the preferred ceiling
        # should finish promptly rather than trigger regeneration or `limited`.
        template_ok = all(
            (
                canonical_present,
                canonical_order,
                canonical_items_present,
                canonical_items_order,
                exact_heading_counts,
            )
        )
        passed = (
            score >= self.thresholds['format_integrity']
            and template_ok
            and exact_capability_direction_set
            and paragraphs_ok
            and no_h1
        )
        suggestions = []
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
        # The historical max-length value is retained only for observability.
        # Do not recommend another compression/edit cycle: once substantive
        # quality passes, an over-target report should be delivered promptly.
        if not exact_capability_direction_set:
            suggestions.append(
                "装备能力图像表只能逐项使用输入的具体武器装备方向，禁止新增装备包、保障节点或C2/网络主体"
            )
        if not no_h1:
            suggestions.append("报告正文不得自行输出一级标题，标题由交付层统一生成")
        return QualityCheck(
            dimension='格式完整性',
            passed=passed,
            score=score,
            indicators=indicators,
            suggestions=suggestions,
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
            "has_5_to_7_equipment_directions",
            "has_at_least_4_direct_combat_weapons",
            "has_no_support_only_main_direction",
            "has_unmanned_combat_equipment",
            "has_remote_precision_missile_equipment",
            "has_query_aligned_offensive_portfolio",
        )
        passed = all(indicators[key] for key in required)
        suggestions: list[str] = []
        if support:
            suggestions.append(
                "以下主体不是直接战斗武器装备，应下沉为体系依赖："
                + "、".join(str(item.get("name", "")) for item in support[:3])
            )
        if len(direct) < 4:
            suggestions.append("至少保留4项直接承担打击、突防、压制、猎歼、毁伤或拦截的具体武器")
        if strike_focused and not defensive_focus and len(offensive) < 4:
            suggestions.append("精确打击主题中至少4项应是进攻性远程/无人火力方向，防御装备不能挤占主体")
        if not unmanned:
            suggestions.append("补充至少1项无人作战平台或巡飞弹武器方向")
        if not missile:
            suggestions.append("补充至少1项独立远程精确制导导弹/弹药方向")
        return QualityCheck("领域属性符合性", passed, score, indicators, suggestions)

    def _check_capability_image_fitness(
        self,
        report: str,
        metadata: dict | None,
    ) -> QualityCheck:
        records = self._expected_capability_records(metadata)
        rows = self._capability_image_table_rows(report)
        names = [str(item.get("name", "")).strip() for item in records]
        row_names = [row[0] for row in rows if row]
        indicator_cells = [row[2] for row in rows if len(row) >= 3]
        concept_cells = [row[3] for row in rows if len(row) >= 4]
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
            "has_capability_domain_and_lineage_position": "能力域" in report
            and any(term in report for term in ("谱系位置", "装备谱系", "相对现有装备")),
        }
        score = sum(indicators.values()) / len(indicators)
        passed = all(indicators.values())
        suggestions = []
        if not indicators["has_exact_equipment_direction_set"]:
            suggestions.append("⑦第一列必须逐项等于能力画像中的具体装备名称，不得改成能力、网络或装备包")
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
        section = self._section_body(report, "⑧ 效能贡献评估", "⑨ 发展优先级与近期抓手")
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
            suggestions.append("⑧必须逐项说明每种装备对杀伤链和作战体系的贡献")
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
        innovation_sections = " ".join(
            (
                self._section_body(report, "② 新战法或新概念技术及制胜机理", "③ 装备能力特征清单"),
                self._section_body(report, "⑧ 效能贡献评估", "⑨ 发展优先级与近期抓手"),
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
            suggestions.append("至少自然形成3类不同关系跃迁，并落实到具体装备，不得罗列方法论标签")
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
        section = " ".join(
            (
                self._section_body(report, "④ 能力实现途径", "⑤ 核心技术清单与攻关优先级"),
                self._section_body(report, "⑤ 核心技术清单与攻关优先级", "⑥ 技术耦合与短板风险"),
                self._section_body(report, "⑥ 技术耦合与短板风险", "⑦ 装备能力图像"),
                self._section_body(report, "⑨ 发展优先级与近期抓手", None),
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
            suggestions.append("④—⑥和⑨需逐项覆盖主要装备方向，不得只给通用技术模板")
        if not indicators["has_evidence_boundary"]:
            suggestions.append("成熟度结论必须标注公开证据、推断和待验证边界，禁止把概念写成既成能力")
        if not indicators["has_validation_and_failure_conditions"]:
            suggestions.append("近期抓手需同时给出演示/靶场/半实物等验证方式，以及通过条件、失败条件或验收判据")
        return QualityCheck("可实现性（成熟度）", passed, score, indicators, suggestions)

    @staticmethod
    def _capability_image_table_directions(report: str) -> list[str]:
        return [row[0] for row in ReportQualityGate._capability_image_table_rows(report)]

    @staticmethod
    def _capability_image_table_rows(report: str) -> list[list[str]]:
        match = re.search(
            r"^###\s*⑦\s*装备能力图像\s*$\n(?P<body>.*?)(?=^###\s*⑧\s*效能贡献评估\s*$)",
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
                "电子压制器", "武器站", "发射单元", "战斗机", "轰炸机",
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
        return any(term in text for term in ("无人机", "无人艇", "无人潜航器", "无人僚机", "无人集群", "蜂群", "巡飞弹"))

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
        section = re.search(
            r"^###\s*⑦\s*装备能力图像\s*$\n(?P<body>.*?)(?=^###\s*⑧\s*效能贡献评估\s*$)",
            report,
            flags=re.MULTILINE | re.DOTALL,
        )
        body = section.group("body") if section else ""
        directions = ReportQualityGate._capability_image_table_directions(report)
        return (
            5 <= len(directions) <= 7
            and "能力域" in body
            and any(term in body for term in ("指标画像", "指标特征", "指标谱"))
            and sum(
                term in body
                for term in ("作战运用", "运用概念", "编组", "波次", "待机", "发射", "突防", "交战", "巡飞")
            ) >= 2
        )

    @staticmethod
    def _has_three_track_winning_effect(report: str) -> bool:
        return (
            any(term in report for term in ("效能跃升", "战力跃升", "作战效能跃升"))
            and any(term in report for term in ("跨代优势", "跨代能力", "代际优势"))
            and any(term in report for term in ("开辟新赛道", "新概念赛道", "形成新赛道"))
        )

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
        """生成摘要"""
        lines = [
            f"总体评分: {overall_score:.1%}",
            f"质量门控: {'✅ 通过' if passed else '❌ 未通过'}",
            "",
            *[
                f"{name}: {item.score:.1%} {'✅' if item.passed else '❌'}"
                for name, item in fitness.items()
            ],
            "",
            f"通用深度诊断: {depth.score:.1%} {'✅' if depth.passed else '❌'}",
            f"通用军事价值诊断: {military_value.score:.1%} {'✅' if military_value.passed else '❌'}",
            f"通用新颖性诊断: {novelty.score:.1%} {'✅' if novelty.passed else '❌'}",
            f"通用前瞻性诊断: {foresight.score:.1%} {'✅' if foresight.passed else '❌'}",
            f"格式完整性: {format_integrity.score:.1%} {'✅' if format_integrity.passed else '❌'}",
        ]

        # 添加改进建议
        all_suggestions = (
            [suggestion for item in fitness.values() for suggestion in item.suggestions] +
            format_integrity.suggestions
        )

        if all_suggestions:
            lines.append("")
            lines.append("改进建议:")
            for i, suggestion in enumerate(all_suggestions[:5], 1):
                lines.append(f"  {i}. {suggestion}")

        return '\n'.join(lines)


__all__ = ['ReportQualityGate', 'QualityReport', 'QualityCheck']
