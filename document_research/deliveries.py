"""有界报告交付文件；私有 SQLite 存储避免暴露任意磁盘路径。"""

import csv
import hashlib
import html
import io
import json
import zipfile

MAX_DELIVERY_BYTES = 4 * 1024 * 1024
NAMES = ("report.md", "report.html", "evidence.csv", "report.json")
MEDIA = ("text/markdown", "text/html", "text/csv", "application/json")


def digest(content):
    """计算用于并发编辑的文件版本。"""
    return hashlib.sha256(content.encode()).hexdigest()


def render_files(task):
    """从已校验报告导出文本、网页、证据表与完整结构。"""
    report = task["report"]
    lines = [
        "# 文档研究交付",
        "",
        task["problem"],
        "",
        "> 研究建议，未实测。编辑此文件不会改变原始证据与报告。",
        "",
    ]
    if report.get("summary"):
        lines.extend([report["summary"], ""])
    for claim in report.get("answer", []):
        lines.extend(
            [
                claim["text"],
                "",
                f"> {claim['quote']}",
                f"来源：{claim['source_id']}",
                "",
            ]
        )
    for candidate in report.get("comparisons", []):
        lines.extend([f"## {candidate['name']}", candidate["approach"], ""])
        lines.extend(f"- 优点：{value}" for value in candidate["pros"])
        lines.extend(f"- 局限：{value}" for value in candidate["cons"])
        lines.extend(["来源：" + ", ".join(candidate["source_ids"]), ""])
    for experiment in report.get("experiments", []):
        lines.extend([f"## 实验：{experiment['name']}", ""])
        lines.extend(f"{i + 1}. {value}" for i, value in enumerate(experiment["steps"]))
        lines.extend(f"- 拟定指标：{value}" for value in experiment["metrics"])
        lines.extend(
            [
                "验收条件：" + experiment["acceptance"],
                "来源：" + ", ".join(experiment["source_ids"]),
                "",
            ]
        )
    if report.get("recommendation"):
        lines.extend(
            [
                "## 推荐理由",
                report["recommendation"]["text"],
                "来源：" + ", ".join(report["recommendation"]["source_ids"]),
                "",
            ]
        )
    for field, title in (
        ("assumptions", "假设"),
        ("gaps", "证据缺口"),
        ("warnings", "限制"),
    ):
        lines.extend(
            ["## " + title, *["- " + value for value in report.get(field, [])], ""]
        )
    lines.extend(
        [
            "## 证据关系",
            "```json",
            json.dumps(report.get("graph", []), ensure_ascii=False, indent=2),
            "```",
            "",
        ]
    )
    table = io.StringIO(newline="")
    writer = csv.writer(table)
    writer.writerow(["id", "title", "page", "origin", "source_url", "text"])
    lines.extend(["## 提供给模型的来源", ""])
    for source in report.get("sources", []):
        values = [
            str(source.get(key) or "")
            for key in ("id", "title", "page", "origin", "source_url", "text")
        ]
        writer.writerow(
            [
                "'" + value
                if value.lstrip().startswith(("=", "+", "-", "@"))
                else value
                for value in values
            ]
        )
        lines.extend(
            [
                f"### {source['id']} · {source.get('title', '')}",
                source.get("text", ""),
                "",
            ]
        )
    markdown = "\n".join(lines)
    # 所有来源及模型内容作为文字转义；页面无远程资源或脚本。
    webpage = (
        '<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>文档研究交付</title><style>body{max-width:960px;margin:32px auto;padding:20px;font:16px/1.7 system-ui}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style><body><pre>'
        + html.escape(markdown)
        + "</pre></body></html>"
    )
    values = (
        markdown,
        webpage,
        table.getvalue(),
        json.dumps(report, ensure_ascii=False, indent=2),
    )
    if any(len(value.encode()) > MAX_DELIVERY_BYTES for value in values):
        raise ValueError("交付文件超过 4 MiB 限额。")
    return dict(zip(NAMES, values, strict=True))


class Deliveries:
    def __init__(self, store):
        self.store = store
        with store.connection() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS deliveries (task_id TEXT PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE, report_digest TEXT NOT NULL, files TEXT NOT NULL)"
            )

    def files(self, task):
        """按报告版本生成一次，保留此版本的 Markdown 编辑。"""
        version = digest(json.dumps(task["report"], sort_keys=True, ensure_ascii=False))
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute(
                "SELECT payload FROM tasks WHERE id=?", (task["id"],)
            ).fetchone()
            if not current or json.loads(current[0]) != task:
                raise PermissionError("task changed")
            self.check_evidence(db, task)
            row = db.execute(
                "SELECT report_digest,files FROM deliveries WHERE task_id=?",
                (task["id"],),
            ).fetchone()
            if row and row[0] == version:
                return json.loads(row[1])
            files = render_files(task)
            db.execute(
                "INSERT OR REPLACE INTO deliveries VALUES(?,?,?)",
                (task["id"], version, json.dumps(files, ensure_ascii=False)),
            )
            return files

    def save(self, task, content, expected):
        """事务内比较版本后更新 Markdown，防止丢失并发编辑。"""
        self.files(task)
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute(
                "SELECT payload FROM tasks WHERE id=?", (task["id"],)
            ).fetchone()
            if not current or json.loads(current[0]) != task:
                raise PermissionError("task changed")
            self.check_evidence(db, task)
            row = db.execute(
                "SELECT files FROM deliveries WHERE task_id=?", (task["id"],)
            ).fetchone()
            files = json.loads(row[0])
            if digest(files["report.md"]) != expected:
                raise FileExistsError("交付文件已经变更，请重新打开后再保存。")
            if len(content.encode()) > MAX_DELIVERY_BYTES:
                raise ValueError("交付文件超过 4 MiB 限额。")
            files["report.md"] = content
            db.execute(
                "UPDATE deliveries SET files=? WHERE task_id=?",
                (json.dumps(files, ensure_ascii=False), task["id"]),
            )
            return {"name": "report.md", "content": content, "sha256": digest(content)}

    @staticmethod
    def check_evidence(db, task):
        """在交付事务内核验本地资料版本，阻止已失效证据被保存。"""
        for library_id, revision in task.get("library_revisions", {}).items():
            row = db.execute(
                "SELECT revision FROM libraries WHERE id=?", (library_id,)
            ).fetchone()
            if row is None or row[0] != revision:
                raise PermissionError("library evidence changed")

    def bundle(self, task):
        """只打包当前任务固定交付文件，不含配置或数据库。"""
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, content in self.files(task).items():
                archive.writestr(name, content.encode())
        return output.getvalue()
