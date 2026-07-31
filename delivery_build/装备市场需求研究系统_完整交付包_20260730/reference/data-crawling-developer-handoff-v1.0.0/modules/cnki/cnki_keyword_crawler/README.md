# CNKI Keyword Crawler

这是从当前项目 `scripts/crawl` 中分离出来的知网关键词检索与 PDF 下载脚本，可直接复制到其他项目使用。

## 文件

- `cnki_keyword_downloader.py`：主入口，按关键词检索知网文章，按下载量阈值过滤，并下载 PDF 到本地。
- `verify_popup_notifier.py`：检测到知网拼图验证页时弹窗提醒人工处理。
- `verify_popup_demo.py`：弹窗提醒链路的本地自测脚本。
- `move_downloads_by_keyword.py`：按 `spider_dp.log` 中的关键词记录归档已下载 PDF。
- `requirements.txt`：最小运行依赖。

## 环境

- Python 3.8+
- 可用 Chromium 内核浏览器
- 可访问 CNKI 的网络和账号权限

安装依赖：

```bash
pip install -r requirements.txt
```

## 运行

在本目录或目标项目目录中运行：

```bash
python cnki_keyword_downloader.py --keyword "乳腺癌诊疗指南" --min-downloads 1000 --max-pages 3
```

常用参数：

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `--keyword` | `诊疗指南` | 搜索关键词 |
| `--min-downloads` | `1000` | 最低下载量阈值 |
| `--start-page` | `1` | 起始页码 |
| `--max-pages` | `1` | 抓取截止页码 |
| `--url` | 空 | 直接指定知网搜索结果页 URL，跳过首页搜索 |
| `--raw-dir` | `data/raw/cnki` | CNKI 原始采集目录 |
| `--cookie-file` | `cookie.txt` | Cookie 文件路径，默认读取项目根目录下的 `cookie.txt` |

## 登录与输出

脚本会读取项目根目录下的 `cookie.txt`，也可以用 `--cookie-file` 指定其他路径。格式为浏览器 Cookie 字符串：

```text
name1=value1; name2=value2; name3=value3
```

如果没有 `cookie.txt`，会复用浏览器当前登录态；未登录时会等待你在打开的浏览器中手动登录。

默认输出位于 `data/raw/cnki/`：

- `papers/`：下载到的 PDF
- `download_report.json`：本次下载报告，记录关键词、统计、成功和跳过条目
- `fail.txt`：本次失败文献清单
- `logs/spider_dp.log`：运行日志

遇到 `https://bar.cnki.net/bar/verify/` 验证页时，脚本会弹窗提醒，完成拼图后回到终端继续。

## 归档下载文件

按关键词从日志中筛选成功下载记录并迁移 PDF：

```bash
python move_downloads_by_keyword.py --keyword "乳腺癌诊疗指南"
```

归档脚本默认读取 `data/raw/cnki/logs/spider_dp.log`，从 `data/raw/cnki/papers/` 查找文件，并迁移到 `data/raw/cnki/archived_downloads/`。如需自定义位置，可继续使用 `--log`、`--source-dir` 和 `--dest-dir`。
