# 本地开发与发布流程

本地项目为 `/Users/wangchen/equipment research 3`，生产项目为服务器的 `/opt/deep-research`，公开入口为 <https://www.deepquest.space>。

## 日常修改

1. 在本地修改源码、测试和部署配置，并检查 Git 差异。
2. 根据改动范围执行后端测试或前端 lint、单元测试和构建。使用隔离的本地数据验证，避免测试连接生产数据服务。
3. 保存可审查的代码差异和验证结果。用户明确要求部署后，再准备生产发布。

服务器只用于读取线上状态、获取必要日志和交付经过本地验证的版本。不要 SSH 到生产目录现场改功能，也不要通过 `docker exec` 修改运行容器里的代码。

## 服务器代码回同步

1. 只读枚举服务器项目源码、测试、依赖清单和部署配置，排除密钥、数据库、用户资料、输出目录、依赖缓存和构建产物。
2. 生成 SHA-256 清单，将差异文件下载到本地暂存目录并校验。服务器未部署的本地内容也可能有价值，覆盖前必须备份。
3. 覆盖前重新验证服务器清单，并检查本地文件是否在准备期间发生变化。保留本地独有文件，不按服务器缺失项删除本地文件。
4. 完成后逐文件校验，保留差异、备份位置与同步范围；只读检查线上 readiness 与容器身份，确认同步未引发服务重启。

回同步代码不包含生产业务数据迁移，也不复制 `.env.prod` 等凭据到本地开发环境。

## 已授权的发布

### 并发发布互斥与陈旧候选保护

- 生产构建、切换、回滚和发布后验收必须在同一个独占锁作用域内完成；锁文件固定为 `/opt/deep-research/.production-release.lock`。未取得锁时立即停止，不等待并插队：

  ```bash
  exec 9>/opt/deep-research/.production-release.lock
  flock -n 9 || { echo '已有生产发布正在执行，当前候选必须停止并重新预检' >&2; exit 75; }
  ```

- 候选准备时记录 API、Web 与相关 Worker 的容器 ID、镜像 ID和 Compose 配置链。取得锁后、执行第一次 `docker compose up` 前重新读取；任一值变化都说明候选已经陈旧，必须中止并基于最新线上版本重新准备，禁止继续叠加旧的 release/rollback overlay。
- 锁必须持续持有到公网门禁、关键业务冒烟和源码漂移检查全部结束；失败回滚也在同一锁内完成。禁止另一个会话在前一发布尚未验收时运行 `docker compose up`、`restart`、`recreate` 或回滚。
- 原始 `docker compose` 命令不能绕过上述锁与二次身份校验。账号采集、公众号文章等进程内子服务会随 API 容器重建而中断，因此即使镜像内容不变，也不得为“刷新状态”无条件重建 API/Web。

1. 从明确的本地版本和文件清单构建候选镜像，构建与测试期间保持线上服务运行。
2. 保存线上源文件、镜像 ID、相关部署配置和回滚步骤；密钥备份保持私密，不提交到 Git。
3. 验证候选版本、依赖兼容性及 API/worker 版本关系，检查活动任务；需要中断时提前说明影响。
4. 切换到候选版本，验证首页、`/api/system/ready` 和变更涉及的关键流程。失败立即按预先准备的步骤回滚。

### 生产交付硬门禁

- 每个生产候选必须使用新的不可变镜像标签，并显式设置 `DEEP_RESEARCH_RELEASE_ID` 与 `DEEP_RESEARCH_SOURCE_REVISION`；发布号对应一次交付，源码指纹使用 Git commit 或经审阅候选包的 SHA-256。`platform.sh` 会阻止缺少这两项的生产构建。
- Web 与 API 镜像写入 OCI 版本标签；Web 额外公开只含发布号、源码指纹和组件名的 `/release.json`。禁止复用当前运行标签覆盖镜像，也禁止仅凭文件时间或容器重启判定“已更新”。
- 切换前运行 `scripts/production_release_gate.py candidate`。候选镜像 ID 与当前容器相同、标签/源码指纹不符、Web 静态资源闭包不完整或 Nginx 配置失败时，门禁直接拒绝发布。
- 切换后运行 `scripts/production_release_gate.py public`，同时核验公网 `/release.json`、readiness、桌面入口、Android 手机入口和首页直接引用的内容哈希资源。证据 JSON 与发布清单、SHA-256、备份和回滚命令保存在同一候选目录。
- 仅重建本次清单中的服务；API 领域代码变更时，API、平台 Worker、Equipment Worker、Query Worker 及 Agent Worker 必须使用同一镜像 ID。版本不一致视为未完成交付，不允许继续观察运行。
- 发布完成标准不是“Compose 命令成功”，而是候选门禁、公网门禁、容器镜像身份、服务健康、关键业务冒烟和无运行时源码漂移全部通过。任一检查失败立即回滚并保存失败证据。

示例：

```bash
export DEEP_RESEARCH_RELEASE_ID=release-20261111-01
export DEEP_RESEARCH_SOURCE_REVISION="$(git rev-parse HEAD)"
PLATFORM_MODE=prod bash scripts/platform.sh build web

python3 scripts/production_release_gate.py candidate \
  --candidate-image deepquest-web:${DEEP_RESEARCH_RELEASE_ID} \
  --current-container deepquest-web-1 \
  --component web \
  --release-id "$DEEP_RESEARCH_RELEASE_ID" \
  --source-revision "$DEEP_RESEARCH_SOURCE_REVISION" \
  --output ".release-candidates/${DEEP_RESEARCH_RELEASE_ID}/candidate-gate.json"

python3 scripts/production_release_gate.py public \
  --public-url https://www.deepquest.space \
  --readiness-url https://www.deepquest.space/api/system/ready \
  --release-id "$DEEP_RESEARCH_RELEASE_ID" \
  --output ".release-candidates/${DEEP_RESEARCH_RELEASE_ID}/public-gate.json"
```

### Web 静态资源发布门禁

- Web 必须从源码重新构建；禁止在编译后的 JS/CSS 上替换业务文案、重命名 `assets` 目录或直接修改运行容器。Vite 文件名内容哈希已经承担缓存失效职责，编译后重命名会破坏动态依赖和 modulepreload 映射。
- `pnpm run build` 必须执行 `scripts/verify-dist-assets.mjs`，确保 HTML、JS、CSS 中的每个 `/assets...` 或 `assets...` 引用都能在最终 `dist` 中解析。
- 候选镜像切换前必须对镜像文件系统重复执行资源闭包检查；切换后验证手机尺寸的全新会话能够加载登录页，并确认访问日志中没有成批静态资源 404。
- 线上容器的 `.Config.Image`、镜像 ID 与发布清单必须一致；`docker diff` 只能出现 Nginx 运行时目录和入口脚本正常变更。发现 `/usr/share/nginx/html` 或业务配置漂移时，重新创建容器，不在容器内补丁修复。
- 根域名和 `www` 域名应同时具备 DNS 与证书覆盖；若产品只使用 `www`，根域名仍应解析并 301 跳转，避免手机浏览器省略 `www` 后无法访问。

## 2026-10-29 同步基线

本次按用户要求以服务器源码为准回同步，原本地差异另存备份，保留本地独有文件。同步范围与验证结果见项目 `artifacts/server-to-local-sync-20261029/`。备份存于 Git 忽略的 `.migration-backup/server-sync-20261029-172029/`，包含 `local-before.tar.gz`、原文件 SHA-256、服务器文件清单及内容差异。

恢复单个原本地文件时，先查看 `server-vs-local.patch`，再从 `local-before.tar.gz` 提取所需文件到暂存目录比较；不要直接将整份备份解压覆盖当前工作区。
