# reference 目录说明

本目录存放本项目参考的外部实现快照，当前包括：

- `GenericAgent-main/`：外部 GenericAgent 实现参考。
- `pi/`：外部 pi 实现参考。

## 边界约定

- 本目录内容仅作为实现参考，不代表本项目的正式源码边界、架构约定或运行入口。
- 外部实现原有的 `.git` 目录已移除，避免与本仓库 Git 状态绑定。
- 外部实现原有的 `.gitignore` 和 `.gitattributes` 已重命名为 `.gitignore.reference` 和 `.gitattributes.reference`，保留内容作为来源参考，但不再作为本仓库 Git 规则生效。
- 外部实现内保留的 `AGENTS.md`、`.github/`、`.husky/` 等文件属于原项目快照内容，不作为本项目仓库规则使用。
- 本项目的忽略规则只维护在仓库根目录 `.gitignore`。
- 更新参考实现时，优先保留来源目录名称和文件结构；如替换为新快照，需要再次确认其中不包含嵌套 `.git` 目录。
