"""在真实沙盒生成可预览、可下载的多格式验收产物。"""

import base64
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from docx import Document
from docx.shared import Inches
from reportlab.pdfgen import canvas

output = Path("outputs/沙盒功能验收")
output.mkdir(parents=True, exist_ok=True)
data = pd.DataFrame({"format": ["Markdown", "HTML", "PDF", "PNG", "CSV", "XLSX"], "verified": [1] * 6})
data.to_csv(output / "数据表.csv", index=False)
data.to_excel(output / "数据表.xlsx", index=False)

fig, ax = plt.subplots(figsize=(8, 3.8), constrained_layout=True)
fig.set_facecolor("#f8fafc")
ax.bar(data["format"], data["verified"], color=["#2563eb", "#0d9488"] * 3, width=0.55)
ax.set_ylim(0, 1.3)
ax.set_yticks([0, 1], labels=["Pending", "Verified"])
ax.set_title("Sandbox artifact formats", loc="left", weight="bold", pad=16)
ax.spines[["top", "right"]].set_visible(False)
fig.savefig(output / "格式验收图.png", dpi=160)
plt.close(fig)

chart = base64.b64encode((output / "格式验收图.png").read_bytes()).decode()
html = """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>沙盒文件产物验收</title><style>
body{font:16px/1.7 system-ui;background:#f1f5f9;color:#0f172a;margin:0;padding:28px}
main{max-width:850px;margin:auto;background:white;padding:30px;border-radius:18px}
h1{margin-top:0}img{max-width:100%}
button{border:0;border-radius:8px;background:#2563eb;color:white;padding:10px 18px;cursor:pointer}
.badge{display:inline-block;background:#dcfce7;color:#166534;padding:3px 12px;border-radius:30px}
</style><main><span class="badge">文件已实际落盘</span><h1>沙盒工作区与文件产物</h1>
<p>本页、数据表、图表和图文报告由真实沙盒 Python 环境生成。此处为功能验收数据，不是装备研究结论。</p>
<img alt="六种产物格式验收图" src="data:image/png;base64,CHART">
<p><button onclick="document.getElementById('result').textContent='交互验证成功：脚本可以在隔离预览中执行。'">
验证页面交互</button></p>
<p id="result">点击按钮验证隔离预览中的交互。</p></main></html>""".replace("CHART", chart)
(output / "交互页面.html").write_text(html, encoding="utf-8")
(output / "验收说明.md").write_text(
    "# 沙盒文件产物验收\n\n这些文件由沙盒工具生成，可从对话文件面板查看与下载。\n\n"
    "|产物|用途|\n|---|---|\n|HTML|隔离交互预览|\n|PDF|图文报告|\n"
    "|PNG|图表|\n|CSV / XLSX|数据表|\n|Python|可执行代码|\n\n"
    "此数据仅用于功能验收，不构成装备研究结论。\n",
    encoding="utf-8",
)
(output / "分析代码.py").write_text("import pandas as pd\nprint(pd.read_csv('数据表.csv').to_string(index=False))\n")
pdf = canvas.Canvas(str(output / "图文报告.pdf"), pagesize=(595, 842))
pdf.setFont("Helvetica-Bold", 23)
pdf.drawString(46, 777, "Sandbox artifact verification")
pdf.setFont("Helvetica", 12)
pdf.drawString(46, 743, "Generated in the real sandbox. All six artifact formats are available.")
pdf.drawImage(str(output / "格式验收图.png"), 38, 424, width=520, height=247)
pdf.drawString(46, 390, "Read/write, browser preview, online editing, downloads and ZIP archive.")
pdf.drawString(46, 362, "These figures are test data for product verification.")
pdf.save()
document = Document()
document.add_heading("沙盒图文报告验收", 0)
document.add_paragraph("真实沙盒生成的图文文档。图中数据仅用于功能验收。")
document.add_picture(str(output / "格式验收图.png"), width=Inches(6))
document.save(output / "图文报告.docx")
print("Generated:", [p.name for p in output.iterdir()])
