#!/bin/bash
# 报告质量验证脚本

set -e

echo "=========================================="
echo "📋 报告质量验证"
echo "=========================================="
echo ""

# 检查参数
if [ -z "$1" ]; then
    echo "用法: $0 <run_id或report_path>"
    echo ""
    echo "示例:"
    echo "  $0 deep-research-run-20260718"
    echo "  $0 outputs/runs/deep-research-run-20260718/report.md"
    exit 1
fi

RUN_ID_OR_PATH="$1"

# 确定报告路径
if [ -f "$RUN_ID_OR_PATH" ]; then
    REPORT_PATH="$RUN_ID_OR_PATH"
elif [ -d "outputs/runs/$RUN_ID_OR_PATH" ]; then
    REPORT_PATH="outputs/runs/$RUN_ID_OR_PATH/report.md"
else
    echo "❌ 找不到报告: $RUN_ID_OR_PATH"
    exit 1
fi

if [ ! -f "$REPORT_PATH" ]; then
    echo "❌ 报告文件不存在: $REPORT_PATH"
    exit 1
fi

echo "报告路径: $REPORT_PATH"
echo ""

# 运行质量检查
echo "运行质量检查..."
python << PYEOF
import sys
sys.path.insert(0, 'src')

from pathlib import Path
from equipment_deep_research.delivery.quality_gate import ReportQualityGate

# 读取报告
report_path = Path('$REPORT_PATH')
report_text = report_path.read_text(encoding='utf-8')

# 质量检查
gate = ReportQualityGate()
result = gate.validate(report_text)

# 显示结果
print("\n" + "=" * 60)
print("📊 质量检查结果")
print("=" * 60)
print("")
print(result.summary)
print("")

# 详细指标
print("=" * 60)
print("📈 详细指标")
print("=" * 60)
print("")

for dimension, check in [
    ('深度性', result.depth),
    ('军事价值性', result.military_value),
    ('新颖性', result.novelty),
    ('前瞻性', result.foresight),
]:
    print(f"## {dimension} ({check.score:.1%})")
    print("")
    for indicator, value in check.indicators.items():
        status = "✅" if value else "❌"
        print(f"  {status} {indicator}")
    print("")

print("=" * 60)

# 退出码
sys.exit(0 if result.passed else 1)
PYEOF

EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ 质量检查通过"
else
    echo "❌ 质量检查未通过，请根据改进建议修改报告"
fi

echo ""
