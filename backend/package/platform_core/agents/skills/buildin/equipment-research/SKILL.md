---
name: equipment-research
slug: equipment-research
description: "把澄清后的装备研究问题转为正式研究任务。当用户确认要做装备需求、作战场景、技术路径、制胜机理或能力画像的正式研究时使用。"
version: "2026.09.22"
tool_dependencies: ["start_equipment_research"]
---

# 装备研究任务技能

当用户需要一份可审计、可恢复、进入研究工作台的正式装备研究时，使用此技能。

## 可用工具

- `start_equipment_research`：在当前用户的 Project 中创建装备研究任务，可选立即排队；`model_spec` 使用平台模型设置中的聊天模型。

## 操作流程

1. 问题含糊时先澄清对象装备、作战场景、研究路线和期望产出。
2. 用户确认后调用 `start_equipment_research`，传入 `project_id` 和澄清后的 `topic`。
3. 把返回的任务入口 `/equipment/runs/<run_id>` 和知识门户 `/knowledge` 告知用户。
4. 不要把对话中的非正式回答伪装成正式研究任务已经完成。

## 关键约束

- 只能为当前用户可访问的 Project 创建任务。
- 历史只读迁移任务不能直接重跑；需要时创建新任务。
- 一般知识问题可以直接回答，不必强制启动研究任务。
