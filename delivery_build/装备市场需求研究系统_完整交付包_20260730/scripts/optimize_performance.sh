#!/bin/bash
# Codex CLI 快速性能优化配置

echo "🚀 应用快速性能优化配置..."
echo ""

# 最大化并发
export EQUIPMENT_DR_MAXIMIZE_AGENT_PARALLELISM=1
export EQUIPMENT_DR_CODEX_PERFORMANCE_PROFILE=balanced

# 证据材料化优化
export EQUIPMENT_DR_EVIDENCE_MATERIALIZE_CONCURRENCY=12
export EQUIPMENT_DR_EVIDENCE_PREWARM_CONCURRENCY=8
export EQUIPMENT_DR_BASELINE_PREFETCH_WORKERS=8

# 证据接受策略（可选，谨慎使用）
# export EQUIPMENT_DR_EVIDENCE_ACCEPT_TARGET=4
# export EQUIPMENT_DR_EVIDENCE_MIN_COUNT=2

echo "✅ 性能优化配置已应用"
echo ""
echo "配置项:"
echo "  - EQUIPMENT_DR_MAXIMIZE_AGENT_PARALLELISM=1"
echo "  - EQUIPMENT_DR_CODEX_PERFORMANCE_PROFILE=balanced"
echo "  - EQUIPMENT_DR_EVIDENCE_MATERIALIZE_CONCURRENCY=12"
echo "  - EQUIPMENT_DR_EVIDENCE_PREWARM_CONCURRENCY=8"
echo "  - EQUIPMENT_DR_BASELINE_PREFETCH_WORKERS=8"
echo ""
echo "预期性能提升:"
echo "  ⚡ Wave 1 执行时间: 减少 50-70%"
echo "  ⚡ 单 agent 时间: 减少 30-40%"
echo "  ⚡ 证据材料化: 减少 40-60%"
echo ""
echo "使用方法:"
echo "  source scripts/optimize_performance.sh"
echo "  python -m equipment_deep_research.interfaces.cli --mode real --topic '...' ..."
