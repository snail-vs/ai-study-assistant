# Agent 驱动的课程设计状态机重构

## 线上兼容性修复记录（2026-09-20）

现网 Provider 可能返回旧版 intake 结构（`ready/stage/brief/nextQuestion`、`value` 选项和 `allowCustomText`）。兼容逻辑集中在 `CourseIntakeAgent` 边界：先做字段映射和确定性归一化，再进入严格 `CourseIntakeStateResult` 校验；无法安全映射的结果统一转为受控的 AI invalid-response 业务错误，不放宽状态和目标字段约束。

## 目标

把当前依赖聊天消息数量和 `ready` 推断的课程设计流程，重构为后端持久化状态机驱动的完整纵向流程：主题 → 学习目标多选与输入 → 个人基础多选与输入 → 需求确认与规模选择 → 大纲生成/修改/确认 → 课程生成。

本次重构必须复用现有项目的 FastAPI/Pydantic/SQLAlchemy、Service、Agent、Pinia、OpenAPI 生成和主题体系，不引入新的通用框架或平行架构。

## 不变量

1. 后端会话快照是流程状态的唯一事实来源；前端不得通过消息数量推断步骤。
2. 前端只发送命令，不直接指定目标状态。
3. Agent 返回建议和内容，不直接写数据库；状态机验证字段白名单和允许转换后才能应用。
4. 学习目标、个人基础均为多选加自定义输入；点击选项不发送请求，点击“下一步”一次提交。
5. 最终需求确认页只展示原始选择，并允许编辑 AI 汇总文本；不再重复提供多选控件。
6. 课程规模默认不选中；AI 推荐只是标签；用户选中后仍需点击“生成课程大纲”。
7. 任何影响大纲的 brief 或规模变化都增加 `brief_revision`；只有 `outline_basis_brief_revision == brief_revision` 的大纲可以确认和生成课程。
8. 未确认大纲不得生成课程；不存在绕过确认的“直接生成课程”。
9. 课程设计 UI 不得使用硬编码深色值，必须使用现有主题入口下的颜色变量。
10. 保留用户已有 `.gitignore` 修改，不提交 `.codegraph/`。

## 持久化状态

- `collecting_goals`
- `collecting_background`
- `reviewing_brief`
- `reviewing_outline`
- `outline_confirmed`
- `course_queued`
- `cancelled`

请求加载和 Agent 调用失败不建立新的业务状态，通过 operation/error 字段表达。

## 命令

- `answer_question`
- `complete_with_ai`
- `go_back`
- `update_brief`
- `select_scale`
- `generate_outline`
- `revise_outline`
- `confirm_outline`
- `generate_course`
- `restart`

## 转换矩阵

| 当前状态 | 命令 | Guard / 副作用 | 下一状态 |
| --- | --- | --- | --- |
| collecting_goals | answer_question | 当前 questionId；目标答案非空；Agent patch 仅目标字段 | collecting_goals / collecting_background |
| collecting_goals | complete_with_ai | Agent 补全有效目标 | collecting_background |
| collecting_goals | restart | 清除会话内容并重新按主题提问 | collecting_goals |
| collecting_background | answer_question | 当前 questionId；基础答案非空；Agent patch 仅基础字段 | collecting_background / reviewing_brief |
| collecting_background | complete_with_ai | Agent 补全有效基础 | reviewing_brief |
| collecting_background | go_back | 保留答案并恢复目标问题 | collecting_goals |
| reviewing_brief | update_brief | 仅允许汇总/需求字段；增加 briefRevision | reviewing_brief |
| reviewing_brief | select_scale | 合法规模；变化时增加 briefRevision | reviewing_brief |
| reviewing_brief | generate_outline | 目标、基础、规模完整 | reviewing_outline |
| reviewing_brief | go_back | 保留内容，恢复基础问题 | collecting_background |
| reviewing_outline | revise_outline | 当前大纲未过期；反馈非空 | reviewing_outline |
| reviewing_outline | generate_outline | 重新生成并记录 basis revision | reviewing_outline |
| reviewing_outline | confirm_outline | 大纲非空且 basis revision 当前 | outline_confirmed |
| reviewing_outline | go_back | 清除/失效大纲 | reviewing_brief |
| outline_confirmed | generate_course | 大纲仍有效；创建 LearningSpace 与后台任务 | course_queued |
| outline_confirmed | revise_outline | 取消确认后修改 | reviewing_outline |
| outline_confirmed | go_back | 取消确认并使大纲失效 | reviewing_brief |

任何不在矩阵中的状态/命令组合返回 409 业务错误。

## API 协议

### 创建会话

`POST /course-design/sessions`

输入 `{ topic }`；输出完整 `CourseDesignSessionResponse`，包含目标问题。

### 获取会话

`GET /course-design/sessions/{session_id}`

用于刷新恢复。

### 执行命令

`POST /course-design/sessions/{session_id}/commands`

请求包含 `commandId`、`expectedRevision`、`type` 和按类型校验的 payload。响应始终返回完整最新快照：state、revision、briefRevision、brief、currentQuestion、recommendedScale、selectedScale、outline、outlineConfirmed、allowedActions。

旧 `/course-design/turn` 在新前端切换后删除；现有 `/outline` 和 `/outline/revise` 的 Agent 能力由 Service 复用，外部流程统一通过命令接口。

## Agent 边界

- CourseIntakeAgent 使用明确 stage 和严格 schema 生成 `briefPatch`、`decision`、当前/下一问题与推荐规模。
- collecting_goals 只允许 patch `learningGoals`、`learningGoalDetails`、`learningOutcome`。
- collecting_background 只允许 patch `priorKnowledgeLevels`、`priorKnowledgeDetails`、`priorKnowledge`。
- Agent 的 nextStage 必须属于当前转换矩阵允许值。
- Agent 失败时会话状态不推进；保留已提交命令/答案用于重试或前端恢复。
- CourseOutlineAgent 继续负责大纲生成与修改，Service 负责版本 Guard。

## 文件边界

### 后端

- `backend/models.py`：增加 CourseDesignSession 持久化字段，不放状态转换代码。
- `backend/migrations/versions/*_add_course_design_sessions.py`：单一迁移及 downgrade。
- `backend/schemas.py`：会话、问题、命令、快照 DTO；维持 alias 惯例。
- `backend/services/course_design.py`：唯一状态机/命令编排位置。
- `backend/course_design_api.py`：只保留 HTTP、鉴权、DTO 和 Service 调用。
- `backend/agents/course_intake_agent.py`、`backend/agents/schemas.py`、`backend/agents/prompts.py`：受约束 Agent 输出。
- `backend/ai/providers/mock.py`、`backend/ai/tasks.py`：复用既有任务路由。
- `backend/tests/test_course_design_state_machine.py`：转换、Guard、版本、越权 patch 测试。
- 现有 intake/outline/learning-space 测试按新契约调整。

### 前端

- `frontend/src/stores/course-design.ts`：只保存后端快照、步骤内本地草稿和命令动作；删除 turnCount/ready 推断。
- `frontend/src/components/course-design/CourseDesignFlow.vue`：按服务端 state 渲染。
- `frontend/src/components/course-design/MultiSelectQuestion.vue`：目标/基础共享，多选不自动提交。
- `frontend/src/components/course-design/CourseBriefReview.vue`：只读选择、可编辑汇总和规模选择。
- `frontend/src/components/course-design/CourseOutlineReview.vue`：大纲生成状态、修改、确认。
- `frontend/src/App.vue`：只挂载 CourseDesignFlow 并处理课程创建完成后的全局刷新。
- `frontend/src/style.css`：在现有主题入口增加/复用 token；课程设计类仅引用变量。
- `frontend/src/stores/course-design.test.ts` 与组件测试：覆盖用户行为。
- `contracts/openapi.yaml`、生成 schema：唯一接口契约来源。

## 实施切片与门禁

### A. 后端协议与状态机

先完成 model/migration/schema/service/API/Agent 约束和后端测试。不得改前端交互。全量后端测试通过后才能进入 B。

### B. 前端纵向流程

基于生成类型完成主题、目标、基础、确认、规模、大纲全链路；组件不直接请求 API。前端测试和 typecheck 通过后进入 C。

### C. 主题变量与旧代码清理

迁移课程设计颜色到 token，验证浅色/深色及响应式；删除旧 turn/quickOptions/turnCount 逻辑和无用样式，运行全量测试和构建。

## 需求追踪与验收

| 需求 | 验收 |
| --- | --- |
| 目标多选 + 输入 | 多选多个 Chip 不产生请求；下一步一次提交全部值与文本 |
| 基础多选 + 输入 | 同上；返回上一步仍保留数据 |
| Agent 针对性 | 问题 options 来自结构化 Agent 输出，target/type 受后端校验 |
| 最终确认职责 | 只有只读选择标签、两个汇总编辑区、规模选择和生成大纲按钮 |
| 推荐非选择 | 初始 selectedScale 为 null，推荐标签不改变它 |
| 大纲一致性 | briefRevision 改变后旧大纲无法确认或生成课程 |
| 状态可靠 | 非法命令 409，过期 expectedRevision 409，重复 commandId 幂等 |
| 浅色主题 | 课程设计卡片、输入、Chip、按钮均使用浅色 token，无黑色硬编码背景 |
| 深色主题 | 保留一致的对比度和选中/禁用/聚焦状态 |
| 课程生成门禁 | 只有 outline_confirmed 才能创建 LearningSpace |

## 最终验证

- 后端全量 unittest。
- Alembic 从空库升级到 head，并验证 downgrade/upgrade。
- OpenAPI 生成文件一致性。
- 前端全量 Vitest、typecheck、build。
- 浏览器人工走通两种主题：主题 → 多选目标 → 多选基础 → 确认 → 选规模 → 生成/修改/确认大纲 → 生成课程。
- `git diff --check`，并检查课程设计样式无硬编码主题色。
