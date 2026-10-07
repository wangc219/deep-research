"""分支交付物验证模块

验证 A/B/C 分支是否满足架构设计的收敛目标。
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_SPECIFIC_WEAPON_EQUIPMENT_TERMS = (
    "无人机",
    "无人艇",
    "无人潜航器",
    "无人车",
    "无人僚机",
    "无人集群",
    "无人作战",
    "巡飞弹",
    "导弹",
    "拦截弹",
    "制导弹药",
    "弹药",
    "鱼雷",
    "火炮",
    "武器站",
    "激光武器",
    "定向能",
    "高功率微波",
    "电子压制",
    "电子战",
    "效应器",
    "防空",
    "雷达",
    "火控",
    "发射单元",
    "作战平台",
)


@dataclass
class ValidationResult:
    """验证结果"""
    branch: str
    passed: bool
    gaps: dict[str, str]
    message: str
    actual: dict[str, int]
    required: dict[str, int]


class BranchDeliverableValidator:
    """
    分支交付物验证器

    基于架构设计要求验证各分支收敛目标：
    - A 分支：3 种新战法、5 种战法组合、8 大能力域、30 项能力指标
    - B 分支：需求卡片、能力全景图、可回溯推理链
    - C 分支：6 条案例规律、3 类未来场景、4 大新兴装备类别
    """

    def validate_branch_a(self, deliverables: dict[str, Any]) -> ValidationResult:
        """
        验证 A 分支（新制胜机理）

        收敛目标：
        - 3 种新战法
        - 5 种战法组合
        - 8 大能力域
        - 30 项能力指标
        - 关联装备形态
        """
        required = {
            'new_tactics': 3,
            'tactic_combinations': 5,
            'capability_domains': 8,
            'capability_metrics': 30,
        }

        actual = {
            'new_tactics': len(deliverables.get('new_tactics', [])),
            'tactic_combinations': len(deliverables.get('tactic_combinations', [])),
            'capability_domains': len(deliverables.get('capability_domains', [])),
            'capability_metrics': len(deliverables.get('capability_metrics', [])),
        }

        gaps = {}
        for key, target in required.items():
            if actual[key] < target:
                gap = target - actual[key]
                gaps[key] = f"{actual[key]}/{target} (缺 {gap})"

        # 检查装备形态关联
        equipment_linked = deliverables.get('equipment_forms_linked', False)
        if not equipment_linked:
            gaps['equipment_forms'] = "未关联装备形态"

        passed = len(gaps) == 0

        message = f"A 分支（新制胜机理）收敛目标: {'✅ 达标' if passed else '❌ 未达标'}"
        if gaps:
            message += f"\n缺口: {gaps}"

        return ValidationResult(
            branch='A',
            passed=passed,
            gaps=gaps,
            message=message,
            actual=actual,
            required=required,
        )

    def validate_branch_b(self, deliverables: dict[str, Any]) -> ValidationResult:
        """
        验证 B 分支（传统场景升级）

        交付物：
        - demand_cards.json（需求卡片）
        - capability_panorama.json（能力全景图）
        - reasoning_traceability.json（推理可回溯）
        """
        required_files = {
            'demand_cards': 'demand_cards.json',
            'capability_panorama': 'capability_panorama.json',
            'reasoning_traceability': 'reasoning_traceability.json',
        }

        gaps = {}
        actual = {}

        # 检查文件是否存在
        for key, filename in required_files.items():
            exists = key in deliverables and deliverables[key] is not None
            actual[key] = 1 if exists else 0

            if not exists:
                gaps[filename] = "缺失"

        # 检查需求卡片结构
        if 'demand_cards' in deliverables:
            cards = deliverables['demand_cards']
            if isinstance(cards, list):
                required_fields = [
                    'weapon_equipment',
                    'equipment_configuration',
                    'development_mode',
                    'key_indicators',
                    'priority',
                    'supporting_scenarios',
                    'evidence_chain',
                ]

                for i, card in enumerate(cards):
                    missing_fields = [f for f in required_fields if f not in card]
                    if missing_fields:
                        gaps[f'card_{i}'] = f"缺少字段: {missing_fields}"
                        continue
                    weapon_equipment = str(card.get('weapon_equipment', '')).strip()
                    has_unmanned_platform = any(
                        term in weapon_equipment
                        for term in (
                            '无人作战',
                            '无人僚机',
                            '无人集群',
                            '无人艇',
                            '无人潜航器',
                            '无人车',
                        )
                    ) or bool(re.search(r'(?<!反)无人机', weapon_equipment))
                    if not has_unmanned_platform and not any(
                        term in weapon_equipment
                        for term in _SPECIFIC_WEAPON_EQUIPMENT_TERMS
                        if term != '无人机'
                    ):
                        gaps[f'card_{i}_weapon_equipment'] = (
                            "主对象不是具体无人、导弹、弹药、火炮、电子战或其他战斗装备"
                        )

        # 检查能力全景图结构
        if 'capability_panorama' in deliverables:
            panorama = deliverables['capability_panorama']
            if not isinstance(panorama, dict):
                gaps['capability_panorama_structure'] = "结构错误：应为对象"
            elif 'domains' not in panorama:
                gaps['capability_panorama_domains'] = "缺少能力域"

        # 检查推理可回溯
        if 'reasoning_traceability' in deliverables:
            trace = deliverables['reasoning_traceability']
            if not isinstance(trace, dict):
                gaps['reasoning_traceability_structure'] = "结构错误"
            elif 'trace_chain' not in trace:
                gaps['reasoning_traceability_chain'] = "缺少推理链"

        passed = len(gaps) == 0

        message = f"B 分支（传统升级）交付物: {'✅ 完整' if passed else '❌ 不完整'}"
        if gaps:
            message += f"\n问题: {gaps}"

        return ValidationResult(
            branch='B',
            passed=passed,
            gaps=gaps,
            message=message,
            actual=actual,
            required={k: 1 for k in required_files.keys()},
        )

    def validate_branch_c(self, deliverables: dict[str, Any]) -> ValidationResult:
        """
        验证 C 分支（案例学习）

        收敛目标：
        - 6 条案例规律
        - 3 类高置信未来场景
        - 4 大新兴装备类别需求图像
        """
        required = {
            'case_patterns': 6,
            'future_scenarios': 3,
            'emerging_equipment_categories': 4,
        }

        actual = {
            'case_patterns': len(deliverables.get('case_patterns', [])),
            'future_scenarios': len(deliverables.get('future_scenarios', [])),
            'emerging_equipment_categories': len(deliverables.get('emerging_equipment_categories', [])),
        }

        gaps = {}
        for key, target in required.items():
            if actual[key] < target:
                gap = target - actual[key]
                gaps[key] = f"{actual[key]}/{target} (缺 {gap})"

        # 检查场景置信度
        if 'future_scenarios' in deliverables:
            scenarios = deliverables['future_scenarios']
            low_confidence = [
                s for s in scenarios
                if isinstance(s, dict) and s.get('confidence', 0) < 0.7
            ]
            if low_confidence:
                gaps['scenario_confidence'] = f"{len(low_confidence)} 个场景置信度 < 0.7"

        passed = len(gaps) == 0

        message = f"C 分支（案例学习）收敛目标: {'✅ 达标' if passed else '❌ 未达标'}"
        if gaps:
            message += f"\n缺口: {gaps}"

        return ValidationResult(
            branch='C',
            passed=passed,
            gaps=gaps,
            message=message,
            actual=actual,
            required=required,
        )

    def validate_all_branches(
        self,
        branch_deliverables: dict[str, dict[str, Any]]
    ) -> dict[str, ValidationResult]:
        """
        验证所有分支

        Args:
            branch_deliverables: {
                'A': {...},
                'B': {...},
                'C': {...},
            }

        Returns:
            {
                'A': ValidationResult(...),
                'B': ValidationResult(...),
                'C': ValidationResult(...),
            }
        """
        results = {}

        if 'A' in branch_deliverables:
            results['A'] = self.validate_branch_a(branch_deliverables['A'])

        if 'B' in branch_deliverables:
            results['B'] = self.validate_branch_b(branch_deliverables['B'])

        if 'C' in branch_deliverables:
            results['C'] = self.validate_branch_c(branch_deliverables['C'])

        return results

    def generate_report(self, results: dict[str, ValidationResult]) -> str:
        """生成验证报告"""
        lines = [
            "=" * 60,
            "分支交付物验证报告",
            "=" * 60,
            "",
        ]

        for branch, result in sorted(results.items()):
            lines.append(f"## {branch} 分支")
            lines.append("")
            lines.append(f"状态: {'✅ 通过' if result.passed else '❌ 未通过'}")
            lines.append("")

            # 完成度
            lines.append("完成度:")
            for key in result.required.keys():
                actual_val = result.actual.get(key, 0)
                required_val = result.required.get(key, 0)
                pct = (actual_val / required_val * 100) if required_val > 0 else 0
                status = "✅" if actual_val >= required_val else "❌"
                lines.append(f"  {status} {key}: {actual_val}/{required_val} ({pct:.0f}%)")

            # 缺口
            if result.gaps:
                lines.append("")
                lines.append("缺口:")
                for key, gap in result.gaps.items():
                    lines.append(f"  ❌ {key}: {gap}")

            lines.append("")
            lines.append("-" * 60)
            lines.append("")

        # 总结
        all_passed = all(r.passed for r in results.values())
        lines.append("## 总结")
        lines.append("")
        lines.append(f"总体状态: {'✅ 所有分支达标' if all_passed else '❌ 部分分支未达标'}")
        lines.append("")

        passed_count = sum(1 for r in results.values() if r.passed)
        total_count = len(results)
        lines.append(f"通过率: {passed_count}/{total_count} ({passed_count/total_count*100:.0f}%)")

        lines.append("")
        lines.append("=" * 60)

        return '\n'.join(lines)


__all__ = ['BranchDeliverableValidator', 'ValidationResult']
