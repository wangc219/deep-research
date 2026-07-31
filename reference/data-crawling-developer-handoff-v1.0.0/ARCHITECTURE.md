# 架构说明

## 设计目标

交接包是源码优先的开发者材料：保留每个站点的原始解析和 CLI，让接手者能够对照测试继续修改；只整合明确重复的基础设施，不把五类采集强行改造成单一框架。

## 分层

```text
crawler.py / handoff CLI
  -> 模块命令映射与 CRAWLER_DATA_ROOT
  -> 原始采集 CLI
  -> 站点专用解析、认证和下载
  -> data/ 输出与 manifest/report

compose browser profile
  -> Xvfb + openbox + x11vnc + noVNC
  -> Chromium / Playwright / DrissionPage
  -> runtime/ session 与人工登录
```

统一启动器只负责把数据根转换为现有参数：期刊 `--output-root/--manifest`、CNKI `--raw-dir`、微信 `--output`、MinerU `--work-root/--artifact-root`、需求挖掘 `--output-root`。

## 共享基础设施

- 期刊模块共享文件名清洗、请求与有限重试、charset 解码、manifest 和断点续跑 helper。
- 需求挖掘模块共享 HTTP transport，统一浏览器风格请求头、最大响应大小、重试、状态码、header 读取、charset 和 JSON 请求。
- 原有可注入 transport、白名单校验、EvidenceCard、排序与模型可见 schema 保持不变。

## 数据隔离

源码、数据和凭据分开挂载：

- `/workspace`：只包含交接源码。
- `/workspace/data`：宿主机 `./data`，由 `CRAWLER_DATA_ROOT` 指向。
- `/workspace/runtime`：宿主机 `./runtime`，保存 session、Cookie 和二维码。
- `/workspace/.env`：宿主机本地 `.env` 的只读挂载。

交接包不解决站点授权、验证码、目标站点改版或 API 配额问题；这些属于真实环境状态，必须在 `LIVE_TEST_REPORT.md` 中如实记录。
