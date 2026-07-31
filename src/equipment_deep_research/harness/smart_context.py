"""上下文智能压缩模块

实现智能上下文摘要和关键信息保留，减少 Recall 率。
预期收益：Recall 率从 30-40% 降低到 < 20%。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import json
import re
from typing import Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class ContextSegment:
    """上下文片段"""
    content: str
    importance: float
    category: str
    metadata: dict[str, Any]


class KeyInformationExtractor:
    """关键信息提取器"""

    def __init__(self):
        # 关键信息模式
        self.key_patterns = {
            'evidence': [
                r'证据[：:]\s*(.+)',
                r'来源[：:]\s*(.+)',
                r'https?://[^\s]+',
            ],
            'conclusion': [
                r'结论[：:]\s*(.+)',
                r'综上[所述]?[，,](.+)',
                r'因此[，,](.+)',
            ],
            'data': [
                r'\d+%',
                r'\d+\s*(秒|分钟|小时|天|年)',
                r'\d+\s*(个|次|项|种)',
            ],
            'capability': [
                r'能力[：:]\s*(.+)',
                r'功能[：:]\s*(.+)',
                r'可以\s*(.+)',
            ],
        }

    def extract(self, text: str) -> list[ContextSegment]:
        """提取关键信息片段"""
        segments = []

        # 按句子分割
        sentences = self._split_sentences(text)

        for sentence in sentences:
            # 计算重要性
            importance, category = self._calculate_importance(sentence)

            if importance > 0.3:  # 阈值
                segments.append(ContextSegment(
                    content=sentence,
                    importance=importance,
                    category=category,
                    metadata={}
                ))

        return segments

    def _split_sentences(self, text: str) -> list[str]:
        """分割句子"""
        # 简单的句子分割
        sentences = re.split(r'[。！？\n]+', text)
        return [s.strip() for s in sentences if s.strip()]

    def _calculate_importance(self, sentence: str) -> tuple[float, str]:
        """计算句子重要性"""
        max_importance = 0.0
        best_category = 'other'

        for category, patterns in self.key_patterns.items():
            for pattern in patterns:
                if re.search(pattern, sentence):
                    # 匹配到关键模式
                    importance = 0.8
                    if importance > max_importance:
                        max_importance = importance
                        best_category = category

        # 基础重要性（长度）
        if max_importance == 0:
            # 中等长度的句子更重要
            length = len(sentence)
            if 20 <= length <= 200:
                max_importance = 0.4
            else:
                max_importance = 0.2

        return max_importance, best_category


class ContextCompressor:
    """
    上下文压缩器

    智能压缩上下文，保留关键信息。
    策略：
    1. 提取关键信息片段
    2. 按重要性排序
    3. 在预算内选择最重要的信息
    """

    def __init__(self, target_ratio: float = 0.5):
        self.target_ratio = target_ratio
        self.extractor = KeyInformationExtractor()
        self.metrics = CompressionMetrics()

    def compress(
        self,
        text: str,
        max_tokens: int,
    ) -> str:
        """
        压缩文本

        Args:
            text: 原始文本
            max_tokens: 最大 token 数

        Returns:
            压缩后的文本
        """
        original_length = len(text)
        self.metrics.original_chars += original_length

        # 如果已经小于目标，直接返回
        estimated_tokens = self._estimate_tokens(text)
        if estimated_tokens <= max_tokens:
            self.metrics.compressed_chars += original_length
            return text

        # 提取关键信息
        segments = self.extractor.extract(text)

        # 按重要性排序
        segments.sort(key=lambda s: s.importance, reverse=True)

        # 选择片段直到达到预算
        selected = []
        current_tokens = 0

        for segment in segments:
            segment_tokens = self._estimate_tokens(segment.content)

            if current_tokens + segment_tokens <= max_tokens:
                selected.append(segment)
                current_tokens += segment_tokens
            else:
                break

        # 按原始顺序重新排序（可选）
        # selected.sort(key=lambda s: segments.index(s))

        # 组合文本
        compressed = '\n'.join(s.content for s in selected)

        compressed_length = len(compressed)
        self.metrics.compressed_chars += compressed_length
        self.metrics.compressions += 1

        compression_ratio = compressed_length / original_length if original_length > 0 else 1.0

        logger.info(
            f"Compressed context: {original_length} → {compressed_length} chars "
            f"({compression_ratio:.1%}), {len(selected)}/{len(segments)} segments"
        )

        return compressed

    def _estimate_tokens(self, text: str) -> int:
        """估算 token 数"""
        # 简单估算：中文 1 char ≈ 1.5 tokens，英文 1 char ≈ 0.25 tokens
        chinese_chars = len(re.findall(r'[一-鿿]', text))
        english_chars = len(text) - chinese_chars

        estimated = chinese_chars * 1.5 + english_chars * 0.25
        return int(estimated)

    def stats(self) -> dict[str, Any]:
        """统计信息"""
        compression_ratio = (
            self.metrics.compressed_chars / self.metrics.original_chars
            if self.metrics.original_chars > 0
            else 1.0
        )

        return {
            'compressions': self.metrics.compressions,
            'original_chars': self.metrics.original_chars,
            'compressed_chars': self.metrics.compressed_chars,
            'compression_ratio': f"{compression_ratio:.1%}",
            'space_saved': self.metrics.original_chars - self.metrics.compressed_chars,
        }


@dataclass
class CompressionMetrics:
    """压缩指标"""
    compressions: int = 0
    original_chars: int = 0
    compressed_chars: int = 0


class CrossAgentMemory:
    """
    跨 Agent 共享记忆

    允许 Agent 之间共享关键发现，减少重复研究。
    """

    def __init__(self):
        self.shared_findings: dict[str, list[dict]] = defaultdict(list)
        self.access_count: dict[str, int] = defaultdict(int)

    def store_finding(
        self,
        agent_id: str,
        category: str,
        content: dict[str, Any],
    ):
        """存储发现"""
        self.shared_findings[category].append({
            'agent_id': agent_id,
            'content': content,
            'timestamp': json.dumps({'_': 'now'}),  # 简化
        })

        logger.info(f"Agent {agent_id} stored finding in category '{category}'")

    def retrieve_findings(
        self,
        category: str,
        exclude_agent: str | None = None,
    ) -> list[dict]:
        """检索发现"""
        findings = self.shared_findings.get(category, [])

        if exclude_agent:
            findings = [f for f in findings if f['agent_id'] != exclude_agent]

        self.access_count[category] += 1

        return findings

    def get_relevant_context(
        self,
        agent_id: str,
        max_items: int = 5,
    ) -> str:
        """获取相关上下文"""
        context_parts = []

        # 从各个类别获取最新的发现
        for category, findings in self.shared_findings.items():
            # 排除自己的发现
            other_findings = [f for f in findings if f['agent_id'] != agent_id]

            # 取最新的几个
            recent = other_findings[-max_items:]

            for finding in recent:
                context_parts.append(
                    f"[{category}] {finding['agent_id']}: {json.dumps(finding['content'], ensure_ascii=False)}"
                )

        return '\n'.join(context_parts)

    def stats(self) -> dict[str, Any]:
        """统计信息"""
        return {
            'categories': len(self.shared_findings),
            'total_findings': sum(len(findings) for findings in self.shared_findings.values()),
            'access_count': dict(self.access_count),
        }


class SmartContextManager:
    """
    智能上下文管理器

    综合管理上下文，包括：
    1. 智能压缩
    2. 关键信息保留
    3. 跨 Agent 记忆

    预期效果：
    - Recall 率从 30-40% 降低到 < 20%
    - 提升推理质量
    """

    def __init__(
        self,
        compression_ratio: float = 0.6,
        enable_cross_agent_memory: bool = True,
    ):
        self.compressor = ContextCompressor(target_ratio=compression_ratio)
        self.cross_agent_memory = CrossAgentMemory() if enable_cross_agent_memory else None
        self.metrics = ManagerMetrics()

    def prepare_context(
        self,
        agent_id: str,
        raw_context: str,
        token_budget: int,
    ) -> str:
        """
        准备上下文

        Args:
            agent_id: Agent ID
            raw_context: 原始上下文
            token_budget: Token 预算

        Returns:
            准备好的上下文
        """
        parts = []

        # 1. 添加跨 Agent 记忆
        if self.cross_agent_memory:
            shared_context = self.cross_agent_memory.get_relevant_context(agent_id)
            if shared_context:
                parts.append("=== 其他 Agent 的相关发现 ===")
                parts.append(shared_context)
                parts.append("")

        # 2. 压缩原始上下文
        # 预留一些预算给跨 Agent 记忆
        shared_tokens = self._estimate_tokens(parts[0] if parts else '')
        remaining_budget = max(token_budget - shared_tokens, token_budget // 2)

        compressed = self.compressor.compress(raw_context, remaining_budget)
        parts.append("=== 任务上下文 ===")
        parts.append(compressed)

        final_context = '\n'.join(parts)

        self.metrics.contexts_prepared += 1

        logger.info(
            f"Prepared context for {agent_id}: "
            f"{len(raw_context)} → {len(final_context)} chars"
        )

        return final_context

    def store_agent_finding(
        self,
        agent_id: str,
        category: str,
        content: dict[str, Any],
    ):
        """存储 Agent 发现"""
        if self.cross_agent_memory:
            self.cross_agent_memory.store_finding(agent_id, category, content)
            self.metrics.findings_stored += 1

    def _estimate_tokens(self, text: str) -> int:
        """估算 token 数"""
        return self.compressor._estimate_tokens(text)

    def stats(self) -> dict[str, Any]:
        """统计信息"""
        stats = {
            'contexts_prepared': self.metrics.contexts_prepared,
            'findings_stored': self.metrics.findings_stored,
            'compressor': self.compressor.stats(),
        }

        if self.cross_agent_memory:
            stats['cross_agent_memory'] = self.cross_agent_memory.stats()

        return stats


@dataclass
class ManagerMetrics:
    """管理器指标"""
    contexts_prepared: int = 0
    findings_stored: int = 0


__all__ = [
    'SmartContextManager',
    'ContextCompressor',
    'CrossAgentMemory',
    'KeyInformationExtractor',
]
