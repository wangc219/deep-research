#!/bin/bash
# 性能测试和对比脚本

set -e

echo "=========================================="
echo "📊 性能测试和对比"
echo "=========================================="
echo ""

# 配置
TEST_TOPIC="${1:-无人机防御装备需求}"
TEST_MODE="${2:-fake}"
TEST_PROVIDER="${3:-codex}"
TEST_MAX_ROUNDS="${4:-1}"

echo "测试配置："
echo "  主题: $TEST_TOPIC"
echo "  模式: $TEST_MODE"
echo "  Provider: $TEST_PROVIDER"
echo "  最大轮次: $TEST_MAX_ROUNDS"
echo ""

# 创建测试结果目录
RESULT_DIR="test_results/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$RESULT_DIR"

echo "结果目录: $RESULT_DIR"
echo ""

# 1. 基准测试（不启用优化）
echo "=========================================="
echo "🔵 基准测试（优化关闭）"
echo "=========================================="
echo ""

# 关闭所有优化
export EQUIPMENT_DR_MAXIMIZE_AGENT_PARALLELISM=0
unset EQUIPMENT_DR_PERF_MONITOR
unset EQUIPMENT_DR_CODEX_PERF

echo "运行基准测试..."
START_TIME=$(date +%s)

timeout 600 python -m equipment_deep_research.interfaces.cli \
  --mode "$TEST_MODE" \
  --provider "$TEST_PROVIDER" \
  --topic "$TEST_TOPIC" \
  --research-route auto \
  --max-rounds "$TEST_MAX_ROUNDS" \
  2>&1 | tee "$RESULT_DIR/baseline.log" || true

END_TIME=$(date +%s)
BASELINE_TIME=$((END_TIME - START_TIME))

echo ""
echo "基准测试完成"
echo "  耗时: ${BASELINE_TIME}秒"
echo ""

# 2. 优化测试（启用所有优化）
echo "=========================================="
echo "🟢 优化测试（Phase 1-3 启用）"
echo "=========================================="
echo ""

# 启用所有优化
export EQUIPMENT_DR_MAXIMIZE_AGENT_PARALLELISM=1
export EQUIPMENT_DR_EVIDENCE_MATERIALIZE_CONCURRENCY=12
export EQUIPMENT_DR_EVIDENCE_PREWARM_CONCURRENCY=8
export EQUIPMENT_DR_BASELINE_PREFETCH_WORKERS=8
export EQUIPMENT_DR_PERF_MONITOR=1
export EQUIPMENT_DR_CODEX_PERF=1

echo "运行优化测试..."
START_TIME=$(date +%s)

timeout 600 python -m equipment_deep_research.interfaces.cli \
  --mode "$TEST_MODE" \
  --provider "$TEST_PROVIDER" \
  --topic "$TEST_TOPIC" \
  --research-route auto \
  --max-rounds "$TEST_MAX_ROUNDS" \
  2>&1 | tee "$RESULT_DIR/optimized.log" || true

END_TIME=$(date +%s)
OPTIMIZED_TIME=$((END_TIME - START_TIME))

echo ""
echo "优化测试完成"
echo "  耗时: ${OPTIMIZED_TIME}秒"
echo ""

# 3. 生成对比报告
echo "=========================================="
echo "📈 性能对比报告"
echo "=========================================="
echo ""

# 计算改进
if [ $BASELINE_TIME -gt 0 ]; then
    IMPROVEMENT=$((100 - (OPTIMIZED_TIME * 100 / BASELINE_TIME)))
    SPEEDUP=$(echo "scale=2; $BASELINE_TIME / $OPTIMIZED_TIME" | bc)
else
    IMPROVEMENT=0
    SPEEDUP=0
fi

cat > "$RESULT_DIR/report.md" << EOF
# 性能对比报告

## 测试配置
- 主题: $TEST_TOPIC
- 模式: $TEST_MODE
- Provider: $TEST_PROVIDER
- 最大轮次: $TEST_MAX_ROUNDS
- 测试时间: $(date)

## 测试结果

| 指标 | 基准 | 优化后 | 改进 |
|------|------|--------|------|
| 执行时间 | ${BASELINE_TIME}秒 | ${OPTIMIZED_TIME}秒 | ${IMPROVEMENT}% |
| 加速比 | 1.0x | ${SPEEDUP}x | - |

## 详细日志
- 基准测试日志: baseline.log
- 优化测试日志: optimized.log

## 分析

EOF

# 添加分析
if [ $IMPROVEMENT -ge 40 ]; then
    echo "✅ 优化效果显著（>= 40% 提升）" >> "$RESULT_DIR/report.md"
elif [ $IMPROVEMENT -ge 20 ]; then
    echo "✅ 优化效果良好（>= 20% 提升）" >> "$RESULT_DIR/report.md"
elif [ $IMPROVEMENT -ge 10 ]; then
    echo "⚠️ 优化效果一般（>= 10% 提升）" >> "$RESULT_DIR/report.md"
else
    echo "❌ 优化效果不明显（< 10% 提升）" >> "$RESULT_DIR/report.md"
fi

# 显示报告
cat "$RESULT_DIR/report.md"
echo ""

# 4. 提取性能指标
echo "=========================================="
echo "📊 性能指标提取"
echo "=========================================="
echo ""

echo "从日志中提取性能指标..."

# 提取缓存命中率
CACHE_HIT=$(grep -o "命中率: [0-9.]*%" "$RESULT_DIR/optimized.log" | head -1 || echo "N/A")
echo "  授权缓存命中率: $CACHE_HIT"

# 提取 Codex 缓存统计
CODEX_CACHE=$(grep -o "Codex 命令缓存统计" "$RESULT_DIR/optimized.log" || echo "N/A")
if [ "$CODEX_CACHE" != "N/A" ]; then
    echo "  ✅ Codex 缓存已启用"
else
    echo "  ⚠️ Codex 缓存未检测到"
fi

echo ""

# 5. 生成可视化图表（如果有 Python）
if command -v python &> /dev/null; then
    echo "生成性能图表..."

    python << PYEOF
import json

data = {
    'baseline_time': $BASELINE_TIME,
    'optimized_time': $OPTIMIZED_TIME,
    'improvement': $IMPROVEMENT,
    'speedup': $SPEEDUP,
}

with open('$RESULT_DIR/metrics.json', 'w') as f:
    json.dump(data, f, indent=2)

print("  ✅ 指标已保存: metrics.json")
PYEOF
fi

echo ""
echo "=========================================="
echo "✅ 测试完成"
echo "=========================================="
echo ""
echo "结果目录: $RESULT_DIR"
echo ""
echo "文件列表："
ls -lh "$RESULT_DIR"
echo ""
echo "查看报告: cat $RESULT_DIR/report.md"
echo ""
