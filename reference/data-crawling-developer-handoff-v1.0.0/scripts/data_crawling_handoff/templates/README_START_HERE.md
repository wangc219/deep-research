# 数据采集开发者交接包

本包面向接手源码、继续调试和二次开发的 Python 开发者，不是面向终端用户的一键采集产品。包内保留期刊 PDF、CNKI、微信公众号、MinerU 和需求挖掘的原始模块边界，同时提供统一数据根、Docker CLI 和可选 browser/noVNC 环境。

## 1. 首次启动

需要 Docker Desktop 或兼容的 Docker Engine / Compose。Windows、Linux 和 macOS 都运行同一套 Linux 容器。

先创建本地环境文件，不要把真实值提交或重新打包：

```powershell
Copy-Item .env.example .env
```

```sh
cp .env.example .env
```

构建并检查环境：

```text
docker compose build
docker compose run --rm cli python crawler.py doctor
```

如果暂时不使用 Docker，也可以在 Python 3.11+ 环境中执行：

```text
python -m pip install -r requirements.txt
python -m playwright install chromium
python crawler.py doctor
```

## 2. 离线回归

```text
docker compose run --rm cli python -m pytest modules/journal/tests modules/cnki/tests modules/wechat/wechat_mp_collector/tests modules/mineru/tests modules/demand_discovery/tests tests -q
```

测试不需要真实 API Key、Cookie 或远程服务。真实采集结果以 `LIVE_TEST_REPORT.md` 为准。

## 3. 模块运行示例

所有统一入口都接受 `CRAWLER_DATA_ROOT`，容器内默认是 `/workspace/data`。

```text
python crawler.py run journal -- --journal zsdd --max-issues 1 --max-papers-per-issue 1
python crawler.py run cnki -- --keyword 诊疗指南 --max-pages 1
python crawler.py run mineru -- --source-root data/raw/pdfs --dataset-name handoff-smoke --limit 1
python crawler.py run demand -- --mode fake --topic 复杂环境保障需求 --max-rounds 1
```

微信公众号命令的 `--session` 是全局参数，必须放在 `auth/collect` 子命令之前：

```text
python crawler.py run wechat -- --session runtime/sessions/wechat-session.json collect 目标公众号 --max-articles 1 --browser chromium
```

## 4. Browser/noVNC

Docker 对微信公众号和 CNKI 最重要，因为它统一 Chromium、Xvfb、显示环境和人工登录入口；期刊、MinerU 和需求挖掘也可以复用同一 CLI 镜像。

```text
docker compose --profile browser up -d browser
```

浏览器打开 `http://localhost:7900/vnc.html`，再在容器内启动需要可见浏览器的采集命令：

```text
docker compose exec browser python crawler.py run wechat -- --session runtime/sessions/wechat-session.json auth --browser chromium --qr-file runtime/sessions/wx_qrcode.png
docker compose exec browser python crawler.py run cnki -- --keyword 诊疗指南 --max-pages 1
```

## 5. 数据与运行时目录

- `data/raw/`：原始下载和采集结果。
- `data/processed/`：MinerU Markdown、chunk 和其他处理中间产物。
- `data/demand_discovery/`：需求挖掘运行产物。
- `runtime/sessions/`：微信 session、CNKI Cookie、二维码等本地凭据材料；不得重新打包。

## 6. 停止与清理

```text
docker compose --profile browser down
```

该命令不会删除宿主机 `data/` 和 `runtime/`。需要清理采集结果时请先人工确认目录，不要删除源码、`.env` 或仍需复用的 session。

继续阅读：`MODULE_GUIDE.md`、`ARCHITECTURE.md`、`SECURITY.md` 和 `TROUBLESHOOTING.md`。
