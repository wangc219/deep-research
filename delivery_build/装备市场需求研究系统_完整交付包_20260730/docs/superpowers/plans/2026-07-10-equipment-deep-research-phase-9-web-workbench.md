# Phase 9 企业前端研究工作台实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现面向分析师、评审人员、审计人员和管理员的 React 企业研究工作台，覆盖研究创建、实时运行、证据审阅、制胜机理、能力画像、报告评审和系统配置。

**Architecture:** 前端只通过 OpenAPI 生成 client 与后端通信，TanStack Query 保存服务端状态，Zustand 只保存界面偏好。SSE reducer 处理实时通知并精确刷新 query cache；业务判定全部来自后端。

**Tech Stack:** React 19、TypeScript、Vite、React Router、Ant Design 5、lucide-react、TanStack Query、Zustand、React Flow、ECharts、Vitest、Testing Library、Playwright、pnpm。

## Global Constraints

- 首屏是研究任务列表，不建设营销首页。
- 页面适合高频研究操作，使用紧凑表格、tabs、drawer、segmented control、tooltip 和稳定尺寸图标按钮。
- 卡片圆角不超过 8px，不嵌套卡片，不使用装饰性渐变球或单一紫色主题。
- 前端不保存 provider/search 密钥，不直接请求外部研究来源。
- API 类型只由 `apps/web/openapi/openapi.json` 生成。
- 关键页面必须通过 1440×900、1280×800、1024×768 视觉检查。

---

### Task 1: 建立 Web 应用、设计令牌和 API client

**Files:**
- Create: `apps/web/package.json`
- Create: `apps/web/pnpm-lock.yaml`
- Create: `apps/web/tsconfig.json`
- Create: `apps/web/vite.config.ts`
- Create: `apps/web/index.html`
- Create: `apps/web/src/main.tsx`
- Create: `apps/web/src/app/App.tsx`
- Create: `apps/web/src/app/router.tsx`
- Create: `apps/web/src/app/providers.tsx`
- Create: `apps/web/src/styles/tokens.css`
- Create: `apps/web/src/styles/global.css`
- Create: `apps/web/scripts/generate-api.mjs`
- Test: `apps/web/src/app/App.test.tsx`

**Interfaces:**
- Consumes: Phase 8 `openapi.json`。
- Produces: `apiClient`、`AppRouter`、`AppShell`、统一 design tokens。

- [ ] **Step 1: 写失败测试固定首屏与布局**

```tsx
it("renders the research task workspace as the first screen", async () => {
  renderApp({ route: "/" });
  expect(await screen.findByRole("heading", { name: "研究任务" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "新建研究" })).toBeInTheDocument();
  expect(screen.queryByText("产品介绍")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: 安装依赖并确认测试因应用不存在而失败**

Run: `pnpm --dir apps/web install && pnpm --dir apps/web test --run`

Expected: 初次 FAIL，随后生成 lockfile。

- [ ] **Step 3: 实现 AppShell 和视觉令牌**

`AppShell` 使用 52px 顶栏、232px 可折叠侧栏和 full-width 内容区。颜色固定为背景 `#F4F6F8`、主文字 `#243447`、主操作 `#2F7185`、成功 `#3F7D5A`、警告 `#A87820`、失败 `#B34A4A`、信息 `#4E6F9E`。全局 `letter-spacing: 0`。

- [ ] **Step 4: 生成 API client 并运行测试**

Run: `pnpm --dir apps/web api:generate && pnpm --dir apps/web test --run`

Expected: PASS，生成目录 `apps/web/src/api/generated/` 不包含手写文件。

- [ ] **Step 5: 验证生产构建**

Run: `pnpm --dir apps/web build`

Expected: 退出码 0，产物位于 `apps/web/dist/`。

### Task 2: 实现身份、权限导航和任务列表

**Files:**
- Create: `apps/web/src/features/auth/useCurrentUser.ts`
- Create: `apps/web/src/features/auth/RequireRole.tsx`
- Create: `apps/web/src/features/runs/RunListPage.tsx`
- Create: `apps/web/src/features/runs/RunTable.tsx`
- Create: `apps/web/src/features/runs/runColumns.tsx`
- Create: `apps/web/src/components/StatusTag.tsx`
- Test: `apps/web/src/features/runs/RunListPage.test.tsx`

**Interfaces:**
- Consumes: `GET /auth/me`、`GET /runs`。
- Produces: 角色化导航、筛选和分页任务表。

- [ ] **Step 1: 写失败测试**

```tsx
it("shows dense run rows and hides admin navigation from analysts", async () => {
  server.use(mockCurrentUser("analyst"), mockRunList([runSummary({ status: "researching" })]));
  renderApp({ route: "/runs" });
  expect(await screen.findByText("低空无人机探测预警能力")).toBeInTheDocument();
  expect(screen.getByText("研究中")).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "系统配置" })).not.toBeInTheDocument();
});
```

- [ ] **Step 2: 运行并确认页面不存在**

Run: `pnpm --dir apps/web test --run RunListPage.test.tsx`

Expected: FAIL。

- [ ] **Step 3: 实现任务列表**

列包含主题、路线、状态、agent、阶段、轮次、证据数、审计、创建人和更新时间。工具栏包含状态/路线/创建人筛选、搜索和刷新；行操作使用 Eye、Play、Pause、RotateCcw、X、Download 图标及 tooltip。

- [ ] **Step 4: 运行任务列表测试**

Run: `pnpm --dir apps/web test --run RunListPage.test.tsx`

Expected: PASS。

- [ ] **Step 5: 验证权限路由**

Run: `pnpm --dir apps/web test --run -t "role|permission"`

Expected: analyst、reviewer、auditor、admin 导航与操作显示符合权限矩阵。

### Task 3: 实现新建研究和动态 Agent coverage

**Files:**
- Create: `apps/web/src/features/runs/CreateRunPage.tsx`
- Create: `apps/web/src/features/runs/ResearchForm.tsx`
- Create: `apps/web/src/features/runs/AgentSelectionTable.tsx`
- Create: `apps/web/src/features/runs/CoveragePanel.tsx`
- Create: `apps/web/src/features/runs/AdvancedRunSettings.tsx`
- Test: `apps/web/src/features/runs/CreateRunPage.test.tsx`

**Interfaces:**
- Consumes: catalog routes/agents/providers、`POST /runs`、`POST /runs/{id}/start`。
- Produces: 可配置研究创建流程。

- [ ] **Step 1: 写失败测试**

```tsx
it("updates capability coverage when agents are selected", async () => {
  server.use(mockCatalog(), mockCreateRun());
  renderApp({ route: "/runs/new" });
  await user.type(screen.getByLabelText("研究主题"), "低空无人机能力需求");
  await user.click(screen.getByRole("checkbox", { name: /国际形势/ }));
  expect(screen.getByText("situation")).toHaveAttribute("data-status", "covered");
  expect(screen.getByText("equipment")).toHaveAttribute("data-status", "missing");
});

it("can create a run with only selected subset agents", async () => {
  renderApp({ route: "/runs/new" });
  await completeFormWithAgents(["combat_scenario", "weapon_equipment"]);
  await user.click(screen.getByRole("button", { name: "创建并启动" }));
  expect(lastCreateRunBody().selected_agent_ids).toEqual(["combat_scenario", "weapon_equipment"]);
});
```

- [ ] **Step 2: 运行并确认失败**

Run: `pnpm --dir apps/web test --run CreateRunPage.test.tsx`

Expected: FAIL。

- [ ] **Step 3: 实现研究表单**

研究路线使用 segmented control；agent 使用可筛选表格和 checkbox；coverage 显示已覆盖、缺失、替代建议；高级设置使用 stepper/input/select，默认轮次 5、并发 4、模型 `gpt-5.5`。提交前调用后端预检，前端不自行判定能否运行。

- [ ] **Step 4: 运行新建研究测试**

Run: `pnpm --dir apps/web test --run CreateRunPage.test.tsx`

Expected: PASS。

- [ ] **Step 5: 验证最长中文标签不溢出**

Run: `pnpm --dir apps/web playwright test tests/create-run-layout.spec.ts`

Expected: 1440、1280、1024 三个视口无文本遮挡，agent 表格列宽稳定。

### Task 4: 实现实时运行控制台与计划图

**Files:**
- Create: `apps/web/src/features/run-console/RunConsolePage.tsx`
- Create: `apps/web/src/features/run-console/RunStatusBar.tsx`
- Create: `apps/web/src/features/run-console/StageNavigation.tsx`
- Create: `apps/web/src/features/run-console/ResearchPlanGraph.tsx`
- Create: `apps/web/src/features/run-console/AgentStatusTable.tsx`
- Create: `apps/web/src/features/run-console/NodeDetailDrawer.tsx`
- Create: `apps/web/src/features/run-console/useRunEvents.ts`
- Create: `apps/web/src/features/run-console/runEventReducer.ts`
- Test: `apps/web/src/features/run-console/RunConsolePage.test.tsx`
- E2E: `apps/web/tests/run-console-live.spec.ts`

**Interfaces:**
- Consumes: run detail/plan/agents/rounds、SSE events、pause/resume/cancel API。
- Produces: 实时可恢复运行视图。

- [ ] **Step 1: 写 SSE reducer 失败测试**

```tsx
it("applies ordered events and ignores duplicate sequence", () => {
  const initial = consoleState({ lastSequence: 10, runStatus: "researching" });
  const changed = reduceRunEvent(initial, runEvent(11, "winning_stage_changed", { stage: "L1" }));
  const duplicate = reduceRunEvent(changed, runEvent(11, "winning_stage_changed", { stage: "L2" }));
  expect(changed.currentStage).toBe("L1");
  expect(duplicate.currentStage).toBe("L1");
});
```

- [ ] **Step 2: 运行并确认失败**

Run: `pnpm --dir apps/web test --run RunConsolePage.test.tsx`

Expected: FAIL。

- [ ] **Step 3: 实现控制台**

React Flow 节点固定尺寸，展示状态、agent、round、输入/输出数量；点击节点打开 drawer。状态栏提供 Pause、Play、RotateCcw、X 图标操作。SSE 断线指数退避并携带 last event id，重连后刷新 run summary 对账。

- [ ] **Step 4: 运行单元与组件测试**

Run: `pnpm --dir apps/web test --run RunConsolePage.test.tsx`

Expected: PASS。

- [ ] **Step 5: 运行实时 E2E**

Run: `pnpm --dir apps/web playwright test tests/run-console-live.spec.ts`

Expected: 创建 run 后计划节点逐步变化；刷新页面后仍显示同一阶段；SSE 重连不重复事件。

### Task 5: 实现证据中心

**Files:**
- Create: `apps/web/src/features/evidence/EvidencePage.tsx`
- Create: `apps/web/src/features/evidence/EvidenceTable.tsx`
- Create: `apps/web/src/features/evidence/EvidenceDetailDrawer.tsx`
- Create: `apps/web/src/features/evidence/QualityScoreBreakdown.tsx`
- Create: `apps/web/src/features/evidence/ConflictComparison.tsx`
- Test: `apps/web/src/features/evidence/EvidencePage.test.tsx`
- E2E: `apps/web/tests/evidence-review.spec.ts`

**Interfaces:**
- Consumes: evidence list/detail、artifact preview。
- Produces: accepted/candidate/rejected、评分、印证、冲突和反证审阅界面。

- [ ] **Step 1: 写失败测试**

```tsx
it("filters evidence and exposes exact source support", async () => {
  server.use(mockEvidenceList(), mockEvidenceDetail("ev-1"));
  renderApp({ route: "/runs/run-1/evidence" });
  await user.click(screen.getByRole("tab", { name: "已接纳" }));
  await user.click(await screen.findByText("ev-1"));
  expect(screen.getByText("质量评分分解")).toBeInTheDocument();
  expect(screen.getByText("正文位置")).toBeInTheDocument();
  expect(screen.getByText("关联 Claim")).toBeInTheDocument();
});
```

- [ ] **Step 2: 运行并确认失败**

Run: `pnpm --dir apps/web test --run EvidencePage.test.tsx`

Expected: FAIL。

- [ ] **Step 3: 实现证据表格和详情**

质量评分使用分段条与数字，不用单一颜色；冲突组展示字段差异和来源；artifact 仅通过后端下载/预览接口加载。大列表使用服务端分页，正文只在 drawer 打开时请求。

- [ ] **Step 4: 运行证据组件测试**

Run: `pnpm --dir apps/web test --run EvidencePage.test.tsx`

Expected: PASS。

- [ ] **Step 5: 运行证据审阅 E2E**

Run: `pnpm --dir apps/web playwright test tests/evidence-review.spec.ts`

Expected: 可筛选状态、打开摘录、查看评分和冲突；rejected evidence 不显示为正式支撑。

### Task 6: 实现制胜机理与能力画像页面

**Files:**
- Create: `apps/web/src/features/winning/WinningPage.tsx`
- Create: `apps/web/src/features/winning/SixStepFlow.tsx`
- Create: `apps/web/src/features/winning/WinningLayerTabs.tsx`
- Create: `apps/web/src/features/winning/GateDecisionPanel.tsx`
- Create: `apps/web/src/features/winning/RecallTimeline.tsx`
- Create: `apps/web/src/features/capabilities/CapabilityPage.tsx`
- Create: `apps/web/src/features/capabilities/CapabilityTable.tsx`
- Create: `apps/web/src/features/capabilities/CapabilityDetailDrawer.tsx`
- Create: `apps/web/src/features/capabilities/TraceabilityFlow.tsx`
- Test: `apps/web/src/features/winning/WinningPage.test.tsx`
- Test: `apps/web/src/features/capabilities/CapabilityPage.test.tsx`
- E2E: `apps/web/tests/capability-image.spec.ts`

**Interfaces:**
- Consumes: winning、recalls、capabilities API。
- Produces: 六步、L1/L2/L3、门控、再调、九字段能力画像和追溯链界面。

- [ ] **Step 1: 写失败测试**

```tsx
it("shows all six reasoning steps and recall return node", async () => {
  server.use(mockWinningDetail());
  renderApp({ route: "/runs/run-1/winning" });
  for (const name of ["防御解构", "制胜路径", "效果链", "能力映射", "差距量化", "图像生成"]) {
    expect(await screen.findByText(name)).toBeInTheDocument();
  }
  expect(screen.getByText("return_node: L1.effect_chain")).toBeInTheDocument();
});

it("separates new capabilities and equipment upgrades", async () => {
  server.use(mockCapabilities());
  renderApp({ route: "/runs/run-1/capabilities" });
  expect(await screen.findByRole("tab", { name: "新作战能力方向" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "现有装备升级需求" })).toBeInTheDocument();
});
```

- [ ] **Step 2: 运行并确认失败**

Run: `pnpm --dir apps/web test --run WinningPage.test.tsx CapabilityPage.test.tsx`

Expected: FAIL。

- [ ] **Step 3: 实现页面**

六步采用稳定横向轨道并在 1024px 切换为两行；L1 淡绿、L2 淡紫灰、L3 淡蓝。能力画像默认紧凑表格，详情 drawer 展示九字段、优先级依据和 EvidenceCard -> packet -> L1 -> L2 -> L3 -> capability 追溯图。

- [ ] **Step 4: 运行组件测试**

Run: `pnpm --dir apps/web test --run WinningPage.test.tsx CapabilityPage.test.tsx`

Expected: PASS。

- [ ] **Step 5: 运行能力画像 E2E 和截图检查**

Run: `pnpm --dir apps/web playwright test tests/capability-image.spec.ts`

Expected: 九字段完整、追溯节点可展开、三种视口无重叠或截断。

### Task 7: 实现报告评审、审计和系统配置

**Files:**
- Create: `apps/web/src/features/reports/ReportReviewPage.tsx`
- Create: `apps/web/src/features/reports/AuditChecklist.tsx`
- Create: `apps/web/src/features/reports/ReviewActionPanel.tsx`
- Create: `apps/web/src/features/audit/AuditTracePage.tsx`
- Create: `apps/web/src/features/admin/AgentConfigurationPage.tsx`
- Create: `apps/web/src/features/admin/PermissionMatrix.tsx`
- Create: `apps/web/src/features/admin/ProviderConfigurationPage.tsx`
- Create: `apps/web/src/features/admin/ConfigurationDiffDrawer.tsx`
- Test: `apps/web/src/features/reports/ReportReviewPage.test.tsx`
- Test: `apps/web/src/features/admin/AgentConfigurationPage.test.tsx`
- E2E: `apps/web/tests/report-review.spec.ts`

**Interfaces:**
- Consumes: report/audit/review/configuration API。
- Produces: reviewer 确认、退回和配置 revision 工作流。

- [ ] **Step 1: 写失败测试**

```tsx
it("prevents analysts from approving and allows reviewers", async () => {
  server.use(mockReport(), mockCurrentUser("analyst"));
  renderApp({ route: "/runs/run-1/report" });
  expect(await screen.findByRole("button", { name: "批准报告" })).toBeDisabled();
  server.resetHandlers(mockReport(), mockCurrentUser("reviewer"));
  renderApp({ route: "/runs/run-1/report" });
  expect(await screen.findByRole("button", { name: "批准报告" })).toBeEnabled();
});

it("shows configuration revision diff before saving", async () => {
  server.use(mockAgentConfiguration());
  renderApp({ route: "/admin/agents" });
  await user.click(await screen.findByRole("switch", { name: "国际形势" }));
  await user.click(screen.getByRole("button", { name: "保存配置" }));
  expect(screen.getByText("配置变更预览")).toBeInTheDocument();
});
```

- [ ] **Step 2: 运行并确认失败**

Run: `pnpm --dir apps/web test --run ReportReviewPage.test.tsx AgentConfigurationPage.test.tsx`

Expected: FAIL。

- [ ] **Step 3: 实现评审和管理页面**

报告正文只读预览；reviewer 填写意见后批准或退回。配置页面显示 agent × tool 和 agent × object scope 矩阵；provider key 不回显，只提供重新设置动作；保存前展示 revision diff。

- [ ] **Step 4: 运行组件测试**

Run: `pnpm --dir apps/web test --run ReportReviewPage.test.tsx AgentConfigurationPage.test.tsx`

Expected: PASS。

- [ ] **Step 5: 运行报告评审 E2E**

Run: `pnpm --dir apps/web playwright test tests/report-review.spec.ts`

Expected: analyst 提交评审，reviewer 查看五判据并批准，报告状态变为 completed，导出可用。

### Task 8: 完成前端质量门槛

**Files:**
- Create: `apps/web/playwright.config.ts`
- Create: `apps/web/tests/research-lifecycle.spec.ts`
- Create: `apps/web/tests/responsive-layout.spec.ts`
- Create: `apps/web/tests/rbac.spec.ts`
- Create: `apps/web/tests/sse-reconnect.spec.ts`
- Create: `docs/testing/phase-9-test-report.md`

**Interfaces:**
- Consumes: 完整 Web 与 mock/真实测试 API。
- Produces: 前端自动验收和视觉基线。

- [ ] **Step 1: 实现完整研究生命周期 E2E**

流程固定为：登录 analyst -> 创建三路线之一 -> 选择 agent 子集 -> 启动 -> 查看实时 agent -> 审阅证据 -> 查看 recall -> 查看能力画像 -> 提交 reviewer -> reviewer 批准 -> 导出。

- [ ] **Step 2: 实现响应式和无重叠测试**

对任务列表、新建研究、运行控制台、证据、制胜机理、能力画像和报告页面分别在 1440×900、1280×800、1024×768 截图；断言横向滚动只出现在明确的表格容器，正文和操作栏无重叠。

- [ ] **Step 3: 执行前端单元、构建和 E2E**

```bash
pnpm --dir apps/web test --run
pnpm --dir apps/web build
pnpm --dir apps/web playwright test
```

Expected: 全部 PASS。

- [ ] **Step 4: 执行可访问性检查**

Run: `pnpm --dir apps/web playwright test tests/accessibility.spec.ts`

Expected: 核心页面无严重 WCAG AA 违规，所有图标按钮有 accessible name 和 tooltip。

- [ ] **Step 5: 生成 Phase 9 审查包**

报告记录页面清单、角色权限、OpenAPI client hash、单元测试、E2E、三视口截图、SSE 重连和仍待 Phase 10 完成的真实部署联调项。
