"""智能证据质量门控模块

材料化前过滤低质量证据，提高接受率和效率。
预期收益：接受率从 60-80% 提升到 85%+，节省 5-10秒/agent。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import re
from typing import Any
from urllib.parse import urlparse
import logging

logger = logging.getLogger(__name__)


# 常见低质量域名黑名单
LOW_QUALITY_DOMAINS = {
    'pinterest.com',
    'instagram.com',
    'facebook.com',
    'twitter.com',
    'reddit.com',  # 社交媒体，非官方来源
    'youtube.com',  # 视频平台
    'amazon.com',   # 电商
    'ebay.com',
    'aliexpress.com',
}

# 高质量域名白名单
HIGH_QUALITY_DOMAINS = {
    'gov',          # 政府网站
    'mil',          # 军事网站
    'edu',          # 教育机构
    'defensenews.com',
    'janes.com',
    'sipri.org',
    'rand.org',
    'cnas.org',
}


@dataclass
class EvidenceScore:
    """证据质量评分"""
    url_score: float
    domain_score: float
    content_score: float
    recency_score: float
    total_score: float
    reasons: list[str]


class QuickFilter:
    """快速过滤器基类"""

    def apply(self, candidates: list[Any]) -> list[Any]:
        """应用过滤器"""
        raise NotImplementedError


class URLValidityFilter(QuickFilter):
    """URL 有效性过滤器"""

    def apply(self, candidates: list[Any]) -> list[Any]:
        """过滤无效 URL"""
        filtered = []

        for candidate in candidates:
            url = self._extract_url(candidate)
            if self._is_valid_url(url):
                filtered.append(candidate)
            else:
                logger.debug(f"Filtered invalid URL: {url}")

        return filtered

    def _extract_url(self, candidate: Any) -> str:
        """提取 URL"""
        if hasattr(candidate, 'source_url'):
            return str(candidate.source_url)
        elif hasattr(candidate, 'url'):
            return str(candidate.url)
        elif isinstance(candidate, dict):
            return str(candidate.get('source_url', candidate.get('url', '')))
        return str(candidate)

    def _is_valid_url(self, url: str) -> bool:
        """检查 URL 是否有效"""
        if not url or not isinstance(url, str):
            return False

        try:
            parsed = urlparse(url)
            # 必须有 scheme 和 netloc
            if not parsed.scheme or not parsed.netloc:
                return False
            # 只接受 http/https
            if parsed.scheme not in ('http', 'https'):
                return False
            return True
        except Exception:
            return False


class DomainReputationFilter(QuickFilter):
    """域名信誉过滤器"""

    def __init__(self):
        self.low_quality = LOW_QUALITY_DOMAINS
        self.high_quality = HIGH_QUALITY_DOMAINS

    def apply(self, candidates: list[Any]) -> list[Any]:
        """过滤低质量域名"""
        filtered = []

        for candidate in candidates:
            url = self._extract_url(candidate)
            domain = self._extract_domain(url)

            # 检查黑名单
            if self._is_blacklisted(domain):
                logger.debug(f"Filtered blacklisted domain: {domain}")
                continue

            filtered.append(candidate)

        return filtered

    def _extract_url(self, candidate: Any) -> str:
        """提取 URL"""
        if hasattr(candidate, 'source_url'):
            return str(candidate.source_url)
        elif hasattr(candidate, 'url'):
            return str(candidate.url)
        elif isinstance(candidate, dict):
            return str(candidate.get('source_url', candidate.get('url', '')))
        return str(candidate)

    def _extract_domain(self, url: str) -> str:
        """提取域名"""
        try:
            parsed = urlparse(url)
            return parsed.netloc.lower()
        except Exception:
            return ''

    def _is_blacklisted(self, domain: str) -> bool:
        """检查是否在黑名单"""
        for blocked in self.low_quality:
            if blocked in domain:
                return True
        return False


class ContentTypeFilter(QuickFilter):
    """内容类型过滤器"""

    def __init__(self):
        # 接受的内容类型
        self.accepted_patterns = [
            r'\.html?$',
            r'\.pdf$',
            r'\.doc[x]?$',
            r'/$',  # 目录页面
            r'^https?://[^/]+$',  # 首页
        ]

        # 拒绝的内容类型
        self.rejected_patterns = [
            r'\.(jpg|jpeg|png|gif|bmp|svg)$',  # 图片
            r'\.(mp4|avi|mov|wmv|flv)$',       # 视频
            r'\.(mp3|wav|ogg)$',                # 音频
            r'\.(zip|rar|tar|gz)$',             # 压缩文件
            r'\.(exe|dmg|apk)$',                # 可执行文件
        ]

    def apply(self, candidates: list[Any]) -> list[Any]:
        """过滤不合适的内容类型"""
        filtered = []

        for candidate in candidates:
            url = self._extract_url(candidate)

            # 检查是否被拒绝
            if self._is_rejected(url):
                logger.debug(f"Filtered rejected content type: {url}")
                continue

            filtered.append(candidate)

        return filtered

    def _extract_url(self, candidate: Any) -> str:
        """提取 URL"""
        if hasattr(candidate, 'source_url'):
            return str(candidate.source_url)
        elif hasattr(candidate, 'url'):
            return str(candidate.url)
        elif isinstance(candidate, dict):
            return str(candidate.get('source_url', candidate.get('url', '')))
        return str(candidate)

    def _is_rejected(self, url: str) -> bool:
        """检查是否被拒绝"""
        url_lower = url.lower()
        for pattern in self.rejected_patterns:
            if re.search(pattern, url_lower):
                return True
        return False


class RecencyFilter(QuickFilter):
    """时效性过滤器"""

    def __init__(self, max_age_years: int = 10):
        self.max_age_years = max_age_years

    def apply(self, candidates: list[Any]) -> list[Any]:
        """过滤过时的内容"""
        # 简单实现：检查 URL 中的年份
        current_year = 2026
        min_year = current_year - self.max_age_years

        filtered = []

        for candidate in candidates:
            url = self._extract_url(candidate)

            # 从 URL 中提取年份
            years = re.findall(r'\b(19|20)\d{2}\b', url)
            if years:
                oldest_year = int(years[0])
                if oldest_year < min_year:
                    logger.debug(f"Filtered outdated content (year {oldest_year}): {url}")
                    continue

            filtered.append(candidate)

        return filtered

    def _extract_url(self, candidate: Any) -> str:
        """提取 URL"""
        if hasattr(candidate, 'source_url'):
            return str(candidate.source_url)
        elif hasattr(candidate, 'url'):
            return str(candidate.url)
        elif isinstance(candidate, dict):
            return str(candidate.get('source_url', candidate.get('url', '')))
        return str(candidate)


class EvidenceQualityPredictor:
    """证据质量预测器"""

    def __init__(self):
        self.domain_stats = defaultdict(lambda: {'accepted': 0, 'total': 0})

    async def score_batch(self, candidates: list[Any]) -> list[tuple[Any, float]]:
        """批量评分"""
        scored = []

        for candidate in candidates:
            score = self._score_one(candidate)
            scored.append((candidate, score.total_score))

        return scored

    def _score_one(self, candidate: Any) -> EvidenceScore:
        """评分单个证据"""
        url = self._extract_url(candidate)
        domain = self._extract_domain(url)

        reasons = []

        # URL 质量评分
        url_score = self._score_url(url, reasons)

        # 域名质量评分
        domain_score = self._score_domain(domain, reasons)

        # 内容质量评分（基于历史）
        content_score = self._score_content(domain, reasons)

        # 时效性评分
        recency_score = self._score_recency(url, reasons)

        # 总分（加权）
        total_score = (
            url_score * 0.2 +
            domain_score * 0.4 +
            content_score * 0.3 +
            recency_score * 0.1
        )

        return EvidenceScore(
            url_score=url_score,
            domain_score=domain_score,
            content_score=content_score,
            recency_score=recency_score,
            total_score=total_score,
            reasons=reasons,
        )

    def _extract_url(self, candidate: Any) -> str:
        """提取 URL"""
        if hasattr(candidate, 'source_url'):
            return str(candidate.source_url)
        elif hasattr(candidate, 'url'):
            return str(candidate.url)
        elif isinstance(candidate, dict):
            return str(candidate.get('source_url', candidate.get('url', '')))
        return str(candidate)

    def _extract_domain(self, url: str) -> str:
        """提取域名"""
        try:
            parsed = urlparse(url)
            return parsed.netloc.lower()
        except Exception:
            return ''

    def _score_url(self, url: str, reasons: list[str]) -> float:
        """URL 质量评分"""
        score = 1.0

        # 检查 URL 长度（过长可能是动态生成）
        if len(url) > 200:
            score *= 0.8
            reasons.append('long_url')

        # 检查参数数量
        param_count = url.count('&') + url.count('?')
        if param_count > 5:
            score *= 0.7
            reasons.append('many_params')

        return max(0.0, min(1.0, score))

    def _score_domain(self, domain: str, reasons: list[str]) -> float:
        """域名质量评分"""
        score = 0.5  # 默认中等

        # 检查白名单
        for quality_suffix in HIGH_QUALITY_DOMAINS:
            if quality_suffix in domain:
                score = 1.0
                reasons.append(f'high_quality_domain:{quality_suffix}')
                break

        # 检查黑名单
        for low_quality in LOW_QUALITY_DOMAINS:
            if low_quality in domain:
                score = 0.2
                reasons.append(f'low_quality_domain:{low_quality}')
                break

        return score

    def _score_content(self, domain: str, reasons: list[str]) -> float:
        """内容质量评分（基于历史）"""
        stats = self.domain_stats.get(domain)
        if stats and stats['total'] >= 3:
            # 有足够的历史数据
            acceptance_rate = stats['accepted'] / stats['total']
            reasons.append(f'historical_rate:{acceptance_rate:.2f}')
            return acceptance_rate

        # 没有足够历史数据，返回中等分数
        return 0.6

    def _score_recency(self, url: str, reasons: list[str]) -> float:
        """时效性评分"""
        current_year = 2026

        # 从 URL 中提取年份
        years = re.findall(r'\b(20\d{2})\b', url)
        if years:
            latest_year = int(years[-1])
            age = current_year - latest_year

            if age <= 2:
                score = 1.0
                reasons.append('recent')
            elif age <= 5:
                score = 0.7
                reasons.append('moderate_age')
            else:
                score = 0.4
                reasons.append('old')

            return score

        # 没有年份信息，返回中等分数
        return 0.6

    def update_stats(self, domain: str, accepted: bool):
        """更新域名统计"""
        self.domain_stats[domain]['total'] += 1
        if accepted:
            self.domain_stats[domain]['accepted'] += 1


class SmartEvidenceGate:
    """
    智能证据质量门控

    材料化前过滤低质量证据，提高接受率。
    预期效果：
    - 接受率从 60-80% 提升到 85%+
    - 节省 5-10秒/agent（减少无效材料化）
    """

    def __init__(self):
        self.quick_filters = [
            URLValidityFilter(),
            DomainReputationFilter(),
            ContentTypeFilter(),
            RecencyFilter(max_age_years=10),
        ]
        self.quality_predictor = EvidenceQualityPredictor()
        self.metrics = GateMetrics()

    async def filter_candidates(
        self,
        candidates: list[Any],
        target_count: int,
    ) -> list[Any]:
        """
        材料化前过滤候选证据

        Args:
            candidates: 候选证据列表
            target_count: 目标接受数量

        Returns:
            过滤后的候选证据列表
        """
        if not candidates:
            return []

        original_count = len(candidates)
        self.metrics.total_input += original_count

        # Phase 1: 快速过滤（< 1ms/candidate）
        filtered = candidates
        for quick_filter in self.quick_filters:
            before = len(filtered)
            filtered = quick_filter.apply(filtered)
            after = len(filtered)
            if before > after:
                logger.info(
                    f"{quick_filter.__class__.__name__} filtered {before - after} candidates"
                )

        quick_filtered_count = len(filtered)
        self.metrics.quick_filtered += (original_count - quick_filtered_count)

        # Phase 2: 质量预测和排序
        if len(filtered) > target_count * 1.5:
            # 批量评分
            scored = await self.quality_predictor.score_batch(filtered)

            # 按质量分数排序
            scored.sort(key=lambda x: x[1], reverse=True)

            # 取前 N 个（适度冗余）
            redundancy_factor = 1.5
            selected_count = min(
                len(scored),
                int(target_count * redundancy_factor)
            )
            filtered = [candidate for candidate, score in scored[:selected_count]]

            self.metrics.quality_filtered += (quick_filtered_count - len(filtered))

            logger.info(
                f"Quality predictor filtered {quick_filtered_count} → {len(filtered)} candidates"
            )

        self.metrics.total_output += len(filtered)

        logger.info(
            f"Smart gate: {original_count} → {len(filtered)} candidates "
            f"(filtered {original_count - len(filtered)}, "
            f"rate {self.metrics.filter_rate():.1%})"
        )

        return filtered

    def update_result(self, domain: str, accepted: bool):
        """更新证据接受结果，用于改进预测"""
        self.quality_predictor.update_stats(domain, accepted)

        if accepted:
            self.metrics.accepted += 1
        else:
            self.metrics.rejected += 1

    def stats(self) -> dict[str, Any]:
        """返回统计信息"""
        return {
            'total_input': self.metrics.total_input,
            'total_output': self.metrics.total_output,
            'quick_filtered': self.metrics.quick_filtered,
            'quality_filtered': self.metrics.quality_filtered,
            'filter_rate': f"{self.metrics.filter_rate():.1%}",
            'accepted': self.metrics.accepted,
            'rejected': self.metrics.rejected,
            'acceptance_rate': f"{self.metrics.acceptance_rate():.1%}",
        }


class GateMetrics:
    """门控指标"""

    def __init__(self):
        self.total_input = 0
        self.total_output = 0
        self.quick_filtered = 0
        self.quality_filtered = 0
        self.accepted = 0
        self.rejected = 0

    def filter_rate(self) -> float:
        """过滤率"""
        if self.total_input == 0:
            return 0.0
        return (self.total_input - self.total_output) / self.total_input

    def acceptance_rate(self) -> float:
        """接受率"""
        total = self.accepted + self.rejected
        if total == 0:
            return 0.0
        return self.accepted / total


__all__ = [
    'SmartEvidenceGate',
    'EvidenceQualityPredictor',
    'QuickFilter',
    'URLValidityFilter',
    'DomainReputationFilter',
    'ContentTypeFilter',
    'RecencyFilter',
]
