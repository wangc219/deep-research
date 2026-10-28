# 视频号转 DOCX

入口为“知识库 · 技能 → 视频号转 DOCX”，地址 `/extensions?tool=wxchannels`。视频发现、临时音频提取、SenseVoice 识别、分段与标点、末尾引导语清理、Word 下载和知识库入库已整合进平台。代码与预编译采集程序随仓库及镜像交付，不依赖原开发电脑或原 `video_text` 目录。

## 网站用户

启用云端共享模式（`WX_CHANNELS_SHARED_CLOUD=true`）后，普通用户只需登录网站，进入“视频号管理”搜索并保存视频号，再选择视频转录、预览、下载 Word 或入库，无需下载本机连接程序。公共视频源由管理员维护的云端微信统一获取；视频目录、完成状态、文字稿和知识库权限仍按网站账号隔离。

管理员首次登录或微信会话过期时，通过 SSH 转发后的私有桌面扫码确认，并打开视频号。网站根据真实代理、证书和微信会话返回状态；掉线时显示等待管理员恢复，不将“容器运行”当作“微信已连接”。该会话不能保证永不过期，管理员需处理微信要求的重新登录。普通用户不能访问云端微信桌面、消息或联系人。

未开启共享模式的部署继续支持以下个人连接流程。

### 在其他电脑连接微信

在云端网站使用时，点击“视频选择”顶部的“连接本机微信”，下载并解压连接包，双击“连接我的微信”，然后返回网页重新检测。连接包必须在登录微信的电脑上运行；云服务器无需登录微信。只点击下载不会建立连接。
连接包自动配置平台地址和设备凭据，支持 macOS Intel/Apple Silicon 与 Windows x64/ARM64。首次系统确认与微信登录由本人完成，后续复用环境。
请保持连接窗口运行。连接包含专用设备凭据，不要转发；可在连接状态栏点击“断开连接”撤销当前电脑配对。凭据不能登录平台或调用普通管理接口。

视频只生成临时音频，音频交接给平台后由 SenseVoice 识别并输出 DOCX，不保存原视频。完成、失败或取消后清理临时音频。

## 云端部署

平台的生产部署入口保持不变：`PLATFORM_MODE=prod bash scripts/platform.sh start`；既有云部署使用 `bash scripts/cloud.sh up -d --build`。

API 镜像构建会完成以下准备：

- 从仓库源码构建四种桌面采集程序并加入一键连接包。
- 安装 FFmpeg、中文字体，以及独立 Python 3.12 的 SenseVoice 运行环境。平台现有模型依赖不受其旧版 transformers 依赖影响。
- x86 Linux 使用 PyTorch CPU 包，避免下载不需要的 CUDA 依赖。

个人模式不要求在云服务器安装或登录微信，也不要求部署中心采集器。网站正常提供 HTTPS、API、Worker、PostgreSQL、Redis 和 MinIO 即可。

建议完整平台至少 4 核、16 GB 内存及 30 GB 可用磁盘；8 GB 环境应减少其他本地解析和图谱任务的并发。SenseVoice 识别与标点分进程依次执行，避免两个模型同时占用内存；识别任务容量固定为 1，其他视频任务进入持久队列。识别操作不占用 API 事件循环。模型缓存在共享的 `outputs/video-models/`，首次下载后复用，不应放入临时容器文件系统。

生产 Nginx 对临时音频接口单独允许 256 MB 上传，支持最长两小时的 16 kHz 单声道 PCM 音轨；其他接口继续采用原平台限制。使用自建反向代理时，也应为 `/api/knowledge/wxchannels/collector/audio` 配置相应大小与传输超时。

### 集中采集器与网站在同一设备

将 `WX_CHANNELS_MCP_URL` 配置为采集器的 MCP 地址。Docker 默认通过 `http://host.docker.internal:2022/mcp` 连接宿主机。桌面采集器源码在 `vendor/wx_channels_download/`：

```sh
bash scripts/video-channels.sh build
bash scripts/video-channels.sh start
```

该模式保留采集程序本身的首次微信、证书和系统权限要求。

### 集中采集器连接远程云服务器

仓库提供仅暴露 SSH 的可选桥接容器。视频 HTTP/MCP 端口只在平台容器网络内可见，不向公网开放。

1. 在集中采集电脑生成专用 SSH 密钥，把公钥文件复制到云服务器。在云端 `.env.prod` 配置 `VIDEO_BRIDGE_AUTHORIZED_KEYS_FILE` 为公钥的绝对路径，按需配置 `VIDEO_BRIDGE_SSH_PORT`（默认 2222）。私钥留在采集电脑。
2. 云端执行：

```sh
VIDEO_CENTRAL_BRIDGE=1 bash scripts/cloud.sh up -d --build api worker video-bridge
```

3. 采集电脑启动微信和本机采集器，运行：

```sh
bash scripts/video-channels-tunnel.sh 云服务器地址 /完整路径/专用SSH私钥
```

首次连接需核对云端桥接容器的 SSH 主机密钥指纹。桥接只允许公钥认证和指定的反向转发，不提供交互式 Shell。平台通过内部 `http://video-bridge:2022/mcp` 访问采集器。个人模式不需要这个桥接。

### Linux Docker 云端共享微信

现有 Linux amd64 云服务器可部署 `compose.wx-collector.yaml`：原生 Linux 微信运行在容器桌面中，集中采集程序提供内部 MCP 接口。构建前准备已审核的 `vendor/wx_channels_download` 源码及 Go vendor 依赖到上下文 `collector-source/`，并放入腾讯官方 `WeChatLinux_x86_64.deb`。运行 `scripts/build-cloud-wechat.sh /absolute/prepared-context`；CGO 必须开启，SQLite 不支持本项目的无 CGO 构建。

在 `.env.prod` 设置 `WX_CHANNELS_MCP_URL=http://wx-collector:2022/mcp` 和 `WX_CHANNELS_SHARED_CLOUD=true`，然后执行 `CLOUD_WECHAT_COLLECTOR=1 bash scripts/cloud.sh up -d wx-collector`。首次切换 API 与通用 Worker 也需更新并同时重建，确保注册集中发现任务。不要重建持久数据目录。

桌面只监听服务器 `127.0.0.1:6300`；管理员使用 `ssh -N -L 16300:127.0.0.1:6300 user@server` 后访问本机 `http://127.0.0.1:16300/` 登录微信并打开视频号。2022/2023 端口不发布公网。容器只取得自身网络命名空间的 TUN 权限，无 privileged 或宿主机网络；每节点生成专属证书且仅在容器内信任。启动微信前自动校准容器内系统代理，避免上游 TUN 模式跳过系统代理配置。

共享源发现全局串行，60 秒元数据快照只供同批排队请求复用；稍后的主动刷新及全量同步仍请求源站。快照不含用户身份、完成标记、文字稿或私有目录 ID。转录另用容量槽位与现有 CPU/内存调度，不占用聊天 Worker。4核16GB 环境下集中微信容器限3GB、1.25CPU；保留主站与模型的调度空间。

### 按需加载视频列表

首次添加先保存视频号，默认最多获取最新两页。数量支持5、10、15、20、30、40、50、100、150和全部；较大数量按需增加页数，普通获取最多十页。“全部”针对当前已加载的未转录视频，完整同步历史需在视频号管理的菜单中单独发起。

“加载更多历史”从本人上次的源游标继续，每批两页；更新最新不会覆盖已推进的历史位置，扩大最新范围会推进到更远位置。Redis保存每个私有目录的游标，PostgreSQL按用户目录和视频ID合并元数据，重叠页、置顶和重复更新不会产生重复记录。已加载视频的nonce等公开身份元数据短期复用，转录不再为查找已选内容遍历全量历史。页面显示排队和获取阶段，并可停止请求。
