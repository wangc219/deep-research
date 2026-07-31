# 数据采集开发者交接包真实环境测试报告

测试日期：2026-07-10（Asia/Shanghai）

状态定义：`passed`、`failed`、`needs_auth`、`blocked_external`、`not_run`。本报告仅记录脱敏命令和相对证据路径，不包含 API Key、Cookie、session 内容、二维码或临时下载 URL。

## 汇总

| 模块 | 状态 | 证据与结论 |
| --- | --- | --- |
| 离线完整回归 | passed | 采集相关基线与新增测试共 `121 passed` |
| ZSDD 期刊 PDF | passed | `journal/zsdd/2026-03/papers/`；1 个文件，大小 2,126,335 bytes，文件头 `%PDF` |
| KTFY 期刊 PDF | passed | `journal/ktfy/2026-02/papers/`；1 个文件，大小 2,997,623 bytes，文件头 `%PDF` |
| 航空学报 PDF | passed | `journal/hkxb/2026-11/papers/`；1 个文件，大小 7,023,298 bytes，文件头 `%PDF` |
| 万方期刊 PDF | blocked_external | 2022-01 与 2025-01 均返回 HTML 而非 PDF；期次发现正常，未把失败内容当 PDF 保存 |
| 共享 HTTP transport | passed | RAND 公开页 HTTP 200，最终 host 为 `www.rand.org`，63,999 bytes，未截断 |
| Tavily | passed | 单次查询、`max_results=1`，返回 1 条结果；未记录 key 或请求头 |
| MLPLA 真实采集 | passed | “装备”查询返回 3 个文档，其中 1 个正文可读；通过 `document_id` 深读 2 段，路线为 `mlpla_search_pdf_body_allowed` |
| MinerU API | passed | 清除旧进程环境变量后从仓库 `.env` 读取新 token；真实单 PDF 成功上传与解析，生成 1 份 Markdown、32 个 chunks，汇总为 `queued=1`、`saved=1`、`batch_failed=0`；证据见 `mineru-retry-envfile-20260711/work/live-smoke/mineru_raw/_api_batch_report.jsonl` |
| Docker amd64 镜像 | passed | CLI/browser 镜像构建成功；Python 3.11、Chromium、Playwright、DrissionPage、noVNC 依赖可用 |
| Docker CLI doctor | passed | 容器内所有依赖、数据卷和 runtime 目录检查通过；仅报告环境变量名 |
| browser/noVNC | passed | browser 容器 healthy；`http://localhost:7900/vnc.html` 返回 HTTP 200；启动脚本 `sh -n` 通过 |
| 微信公众号 | needs_auth | 现有 session 已失效；noVNC 扫码窗口已验证可启动，但本次未在 5 分钟窗口内完成扫码 |
| CNKI | needs_auth | 修复 Linux Chromium 参数后成功启动浏览器、进入搜索页、识别 20 条结果；多次 PDF 下载均未落地，未获得有效 PDF |
| linux/amd64 + linux/arm64 | blocked_external | buildx builder 声明支持两平台；arm64 基础镜像层因本机 Docker Hub 直连超时无法拉取，未声称完成 arm64 构建 |
| 净室 ZIP | passed | r2 净室解压后 228 个 checksum 一致、敏感文件/PDF 为 0、Compose 重建与 doctor 通过、包内测试 `121 passed` |

## 脱敏命令摘要

```text
python scripts/journal/download_all_journals.py --journal <slug> --max-issues 1 --max-papers-per-issue 1 --output-root <LIVE>/journal
python scripts/extraction_experiment/prepare_chunks.py --source-root <SMALL_PDF_DIR> --work-root <LIVE>/mineru/work --limit 1
docker compose --profile browser build --pull=false
docker compose run --rm cli python crawler.py doctor
docker compose --profile browser up -d browser
docker compose exec browser python crawler.py run cnki -- --keyword 诊疗指南 --max-pages 1
docker buildx build --platform linux/amd64,linux/arm64 ... --output type=oci,dest=<LIVE>/multiarch.oci
```

## 限制

- 微信和 CNKI 的未通过项属于认证/站点访问状态，不能描述为采集成功。
- MinerU token 读取遵循“当前进程环境变量优先于 `.env`”；若更新 `.env` 后仍收到 401，应先清除终端中遗留的 `MINERU_TOKEN` 再复测。本次仅在验证子进程中清除旧值，未输出或写入任何 token。
- arm64 失败点是 Docker Hub 基础镜像拉取网络，不是本地 builder 缺少 arm64 能力；仍需在可访问 registry 的环境复测。
