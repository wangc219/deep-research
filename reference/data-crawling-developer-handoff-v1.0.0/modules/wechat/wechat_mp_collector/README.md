# 微信公众号本地采集工具

这个目录提取了 `we-mp-rss-main` 中微信公众号采集链路的关键逻辑，保留扫码授权，但不依赖 WebUI、FastAPI、Redis 或 SQLite。工具会把公众号文章列表、正文 HTML、Markdown 和 JSONL 保存到本地。

## 工作方式

1. 用 Playwright 打开微信公众平台登录页，保存二维码截图并等待扫码授权。
2. 保存授权后的 `token` 与 cookie 到本目录下的 `data/session.json`。
3. 调用微信公众平台后台接口：
   - `searchbiz` 搜索公众号并获得 `fakeid`。
   - `appmsgpublish` 拉取公众号历史文章列表。
4. 用 Playwright 打开每篇文章 URL，提取 `#js_content` 正文、标题、摘要、发布时间等信息。
5. 输出到仓库根目录 `data/raw/<公众号>/`。

## 常用命令

在仓库根目录执行，推荐使用已验证的 AgentDev 环境(脚本作者的环境，任意存在依赖的环境都可用)：

```powershell
C:\Users\HP\anaconda3\envs\AgentDev\python.exe wechat_mp_collector\collect.py auth
```

扫码成功后搜索公众号：

```powershell
C:\Users\HP\anaconda3\envs\AgentDev\python.exe wechat_mp_collector\collect.py search "海鹰资讯"
```

采集海鹰资讯最近 1 页文章并下载正文：

```powershell
C:\Users\HP\anaconda3\envs\AgentDev\python.exe wechat_mp_collector\collect.py collect "海鹰资讯" --pages 1
```

查看内置公众号清单：

```powershell
C:\Users\HP\anaconda3\envs\AgentDev\python.exe wechat_mp_collector\collect.py list-accounts
```

批量采集内置公众号。当前内置账号包括 `防务快讯` 和 `军民融合观察`：

```powershell
C:\Users\HP\anaconda3\envs\AgentDev\python.exe wechat_mp_collector\collect.py collect-many --pages 1
```

只采集内置清单中的指定公众号：

```powershell
C:\Users\HP\anaconda3\envs\AgentDev\python.exe wechat_mp_collector\collect.py collect-many "防务快讯" --pages 1
```

已知 `fakeid` 时可跳过搜索：

```powershell
C:\Users\HP\anaconda3\envs\AgentDev\python.exe wechat_mp_collector\collect.py collect-by-fakeid "MzA5MTM4MTU4MA==" --name "海鹰资讯" --pages 1
```

如果只想复用 WeRSS 已授权会话，可导入 `wx.lic`：

```powershell
C:\Users\HP\anaconda3\envs\AgentDev\python.exe wechat_mp_collector\collect.py import-werss we-mp-rss-main\data\wx.lic
```

## 输出目录

采集产物默认输出到仓库根目录：

```text
data/raw/<公众号>/
  metadata.json
  articles.json
  articles.jsonl
  html/*.html
  markdown/*.md
```

授权会话和二维码仍保存在 `wechat_mp_collector/data/`，该目录已在本工具 `.gitignore` 中忽略。不要把 `session.json`、二维码、cookie 或 token 提交到仓库。

## 参数说明

- `--pages`：采集页数。每页通常最多 5 条图文，默认 1 页。
- `--max-articles`：限制本次实际下载正文的文章数，适合链路测试。
- `--delay`：文章列表接口请求间隔，格式如 `3:8`。
- `--content-delay`：正文下载间隔，格式如 `2:5`。
- `--no-content`：只保存文章列表，不打开文章页下载正文。
- `--headless`：扫码授权默认会打开可见浏览器窗口；加此参数可改为无头模式，并通过二维码截图扫码。
- `collect-many --account-delay`：批量采集时两个公众号之间的间隔，默认 `5:12`。
- `collect-many --stop-on-error`：批量采集时遇到单个账号失败即停止；默认会继续采集后续账号并在末尾汇总失败项。

## 边界

这个工具只做本地化采集和归档，不包含定时任务、Web 管理界面、RSS 服务、数据库状态管理和 Redis 会话刷新。微信公众平台可能触发频率控制或登录失效，出现 `200013` 或 `Invalid Session` 时应降低频率或重新扫码授权。
