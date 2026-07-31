# 真实环境测试报告

离线采集基线：`93 passed`。该数字来自重构前采集相关测试；最终包必须补充重构后的完整离线测试总数。

允许状态：`passed`、`failed`、`needs_auth`、`blocked_external`、`not_run`。报告只能写脱敏命令、相对证据路径和限制，不得记录 token、Cookie、二维码或原始认证请求头。

| 时间 | 模块 | 状态 | 脱敏证据 | 限制 |
| --- | --- | --- | --- | --- |
| 待执行 | 离线完整回归 | not_run | - | 待记录最终测试总数 |
| 待执行 | 期刊 PDF | not_run | - | 待执行每站点最小真实下载 |
| 待执行 | 需求挖掘公开网页/Tavily/MLPLA | not_run | - | 待执行联网 smoke |
| 待执行 | MinerU | not_run | - | 待执行单 PDF API 解析 |
| 待执行 | Docker CLI | not_run | - | 待构建并运行 doctor |
| 待执行 | browser/noVNC | not_run | - | 待验证 7900 页面和容器进程 |
| 待执行 | 微信公众号 | not_run | - | 可能需要扫码 |
| 待执行 | CNKI | not_run | - | 可能需要登录或验证码 |
| 待执行 | linux/amd64 + linux/arm64 | not_run | - | 待 buildx 验证 |
| 待执行 | 净室 ZIP | not_run | - | 待 checksum、扫描和解压测试 |
