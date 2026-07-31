# 模块指南

## 公共入口

| 模块 | 统一名称 | 原始入口 | 主要输出 |
| --- | --- | --- | --- |
| 公开期刊 PDF | `journal` | `modules/journal/scripts/journal/download_all_journals.py` | `data/raw/<journal>/` 与 manifest |
| CNKI 关键词采集 | `cnki` | `modules/cnki/cnki_keyword_crawler/cnki_keyword_downloader.py` | `data/raw/cnki/` |
| 微信公众号 | `wechat` | `modules/wechat/wechat_mp_collector/collect.py` | `data/raw/wechat/` |
| MinerU API | `mineru` | `modules/mineru/scripts/extraction_experiment/prepare_chunks.py` | `data/processed/` |
| 需求挖掘 | `demand` | `modules/demand_discovery/scripts/demand_discovery_autonomous_research.py` | `data/demand_discovery/` |

统一入口为：

```text
python crawler.py run <module> -- <原模块参数>
```

`crawler.py` 只做参数和数据根映射，不改变站点 CLI 的业务语义。遇到参数问题时，先运行 `python crawler.py run <module> -- --help`。

## 内部实现

- `journal_download_common.py`：期刊文件名、HTTP 重试、charset、manifest 和断点续跑 helper。
- `knowledgegraph.demand_discovery.tools.http_transport`：需求挖掘共享 HTTP 响应、重试、截断、解码和 JSON helper。
- `knowledgegraph.demand_discovery.tools.acquisition*`：高层白名单采集、MLPLA 适配和模型可见文档契约。
- `wechat_mp_collector/wechat_mp_collector/`：微信授权、API、正文抓取和本地存储实现。
- `scripts/extraction_experiment/mineru_api_batch.py`：MinerU 上传、轮询、归档和 API report 实现。

这些内部模块适合阅读、测试和二次开发，但不应绕过白名单、凭据隔离、manifest 或证据留痕约束。

## 认证边界

- 期刊脚本仅在目标站点确实需要时传入合法 Cookie 文件。
- CNKI 登录和验证码通过 browser/noVNC 人工完成。
- 微信 session 通过 `--session runtime/sessions/...` 显式传入。
- MinerU 和需求挖掘只读取 `.env` 中已经配置的变量名。
