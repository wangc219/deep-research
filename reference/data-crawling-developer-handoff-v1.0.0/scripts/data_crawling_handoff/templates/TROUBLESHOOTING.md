# 故障排查

## 认证与 session

现象包括缺少 token、Cookie 过期、微信返回登录页、CNKI 跳转登录。先确认传入的是 `runtime/` 下的正确文件，再通过 noVNC 重新授权。不要把认证失败改成跳过校验。

## 反爬、验证码和访问频率

遇到滑块、二维码、频率限制或异常重定向时，降低请求频率并人工完成验证。`needs_auth`、`blocked_external` 和成功状态必须区分记录；dry-run 不能替代真实下载证明。

## 站点改版

先运行对应离线测试，定位是 selector、接口 URL、字段名、分页、PDF 跳转还是 charset 改变。修复时保留原始 manifest 和 transport 注入点，并补充最小回归测试。

## 网络与代理

分别检查 DNS、TLS、系统代理、容器网络、超时和远端状态码。MinerU 默认会清理代理环境；如果所在网络必须使用代理，应显式关闭该行为并记录配置。不要使用无限重试掩盖持续失败。

## Docker 与 noVNC

- `docker compose config` 失败：检查 `.env` 是否存在、YAML 是否被本地修改。
- browser 服务不健康：查看 `docker compose logs browser`，确认 Xvfb、x11vnc 和 websockify 进程。
- noVNC 有桌面但采集器无浏览器：在 browser 容器内执行命令，并为微信显式选择 `--browser chromium`。
- Apple Silicon 构建失败：检查目标依赖是否有 `linux/arm64` wheel 或系统包，并记录 buildx 限制。

## 代码回归判定

只有在离线测试失败、输出路径错误、manifest 不完整、HTTP 解码异常或下载文件不是有效 PDF 时，才判定为代码回归。远端认证、验证码、配额和站点不可用应记录为外部阻塞。
