# 课程设计 Intake：迁移权收回服务端（方案 B）

- 日期：2026-09-22
- 状态：已实施（2026-09-22）
- 关联故障：创建课程回答问题时 422「Agent 必须返回当前阶段的追问」

---

## 1. 背景与问题

### 1.1 产品链路中的 intake

创建课程不是自由对话，而是服务端状态机驱动的动态问卷：

```
topic 输入
  → collecting_goals      （学完能做什么）
  → collecting_background （现有基础）
  → reviewing_brief       （确认 brief + 规模）
  → reviewing_outline     （确认大纲）
  → outline_confirmed
  → course_queued         （异步生成正文）
```

每一步的合法命令写死在 `ALLOWED_ACTIONS`（`backend/services/course_design.py`）。
用户提交 `answer_question` 后，由 `CourseIntakeAgent` 调模型，再由服务端写 brief、迁阶段、出下一题。

**下游（大纲、正文规划）只消费 `CourseBrief` + `course_scale`，从不消费 intake 的 `decision`。**

### 1.2 当前模型协议在做什么

`evaluate_intake_answer` / `start_intake` / `complete_with_ai` 共用 `CourseIntakeStateResult`：

```json
{
  "briefPatch": { "learningOutcome": "..." },
  "decision": { "type": "ask_follow_up|advance", "nextStage": "collecting_goals" },
  "nextQuestion": { "stage": "...", "target": "...", "title": "...", "options": [] },
  "recommendedScale": "standard"
}
```

一次响应里模型同时承担三件事：

| 职责 | 字段 | 性质 |
|------|------|------|
| 信息抽取 | `briefPatch` | 产品资产 |
| 流程裁决 | `decision` | 离散状态迁移建议 |
| 交互出题 | `nextQuestion` | UI 契约 |

其中「答案是否矛盾、是否太糊、要不要再问」属于语义判断，规则写不死，只能靠模型；
但「当前 state、合法边、必填字段是否齐、用户允许哪些命令」是纯规则，服务端已有完整表驱动。

### 1.3 故障根因

`_answer` 在 `course_design.py:330-332`：

```python
if not next_question:
    if next_stage == current_question.get("stage"):
        raise CourseDesignInvalid("Agent 必须返回当前阶段的追问")
```

触发条件：

1. 模型 `nextQuestion` 为 `null`（schema / `normalize_state_result` 均放行）；
2. `decision.type == "ask_follow_up"`（服务端强制 `next_stage = session.state`，必与当前题同阶段）。

协议层允许「说要追问但不给题」的半截响应；
repair（`_missing_transition_summary`）只覆盖 `advance` 缺 `learningOutcome`/`priorKnowledge`；
跨阶段缺题已有 `_fallback_question`（commit `400e307`），**同阶段缺题无 repair、无 fallback，直接 422**。

典型坏返回：

```json
{ "briefPatch": {}, "decision": { "type": "ask_follow_up", "nextStage": "collecting_goals" } }
```

或缺省 `decision` 被 normalize 成 `ask_follow_up` + `nextQuestion: null`（`course_intake_agent.py:100-107,171-172`）。

### 1.4 设计层问题（为何不能只打补丁）

| 问题 | 说明 |
|------|------|
| 双权威 | 模型建议 `decision`，服务端再终审字段与边；两者都像权威，策略纠缠 |
| 不变量未钉死 | `ask_follow_up ⇔ nextQuestion != null` 无 schema/交叉校验 |
| decision 非领域资产 | 下游不读；`complete_with_ai` 路径反而由服务端强制迁移（`course_design.py:361-375`），形态已不一致 |
| 422 暴露给用户 | 文案偏内部协议，用户无法自愈 |

### 1.5 方案取舍

| | A 轻修（保留 decision） | **B 迁移权收回服务端（本方案）** |
|--|------------------------|----------------------------------|
| 改动 | 补 prompt + repair + fallback | 协议瘦身 + 状态迁移单出口 + 测试切换 |
| 「追问无题」 | 堵洞，结构上仍可能再出 | 结构上不存在（stay 必由服务端填题） |
| 职责 | 模型建议 + 服务端审查（双轨） | 模型：语义+数据；服务端：状态机（单轨） |
| 与 complete 路径 | 长期两套心智 | 统一 |

**结论：采用 B。**
另拆一个可先行的止血步（见 §4.1），使 422 可先于全量协议切换消失。

---

## 2. 方案 B 设计

### 2.1 职责划分

```
模型（只保留语义与数据）:
  - briefPatch（含 learningOutcome / priorKnowledge 等）
  - sufficiency: sufficient | needs_clarification   （语义：够不够 / 有无矛盾或太糊）
  - clarificationQuestion: object | null            （仅 needs_clarification 时应非空）
  - 可选 nextStageQuestion: object | null           （sufficient 时下一阶段题草稿，可无）
  - assistantMessage / recommendedScale

服务端（唯一状态机）:
  - 当前 state、合法边、ALLOWED_ACTIONS
  - 必填字段规则 → 是否允许真正 advance
  - stay 时保证 current_question 非空（模型题 or _fallback_question）
  - 幂等 commandId、expectedRevision、字段白名单
  - 防循环：复读题 / 连续 follow-up 计数 / complete 等价推进
```

### 2.2 新协议（概念形状，落地前可微调命名）

```json
{
  "briefPatch": { "learningOutcome": "..." },
  "sufficiency": "needs_clarification",
  "clarificationQuestion": {
    "stage": "collecting_goals",
    "target": "learningGoals",
    "title": "...与已答题实质不同...",
    "options": [{ "id": "...", "label": "..." }]
  },
  "nextStageQuestion": null,
  "assistantMessage": "",
  "recommendedScale": "standard"
}
```

| 字段 | 必填条件 | 服务端用法 |
|------|----------|------------|
| `briefPatch` | 总是 | 白名单合并进 `session.brief`（不变） |
| `sufficiency` | evaluate/complete 总是；start 默认 `needs_clarification` | 语义信号，**不是**迁移权威 |
| `clarificationQuestion` | `sufficiency=needs_clarification` 时应非空 | 缺失 → repair → 仍缺 → `_fallback_question` |
| `nextStageQuestion` | 可选 | sufficient 且字段齐时用于下一阶段；可无 → fallback |
| `decision` | **废弃** | 兼容期双读映射（见 §3.2） |

### 2.3 服务端决策表（`_answer` 核心）

```
输入: stage, brief', answer, 模型响应（新协议或旧映射）

1. 合并 briefPatch（白名单过滤；topic 永不来自模型）

2. 若 sufficiency == needs_clarification:
     且 连续 follow-up 计数 < N（默认 N=2）:
       且 未命中「复读原题」→ complete 路径:
         next_state = stage                    # stay
         question = clarificationQuestion
                    ?? repair 一次
                    ?? _fallback_question(stage, topic)
     否则 fallthrough 到 (3)   # 死循环防护：无视 needs_clarification

3. sufficiency == sufficient，或 (2) 因计数/复读降级:
     若 阶段必填未齐:
       # goals: learningOutcome 或 learningGoals 空
       # background: priorKnowledge 或 priorKnowledgeLevels 空
       → repair 补字段一次；仍不齐 → 按 stay 处理（同 2 的题逻辑），禁止 advance
     若 阶段必填已齐:
       next_state = 合法下一阶段（表驱动，不读模型 nextStage）
         goals → background
         background → reviewing_brief
       question = nextStageQuestion 或 _fallback_question(next_state, topic)
       background→reviewing_brief 时 question 必须为 null（清 current_question）

4. 写库、revision++、快照返回
   永不因「模型缺题」抛 CourseDesignInvalid
```

**硬规则汇总：**

1. `needs_clarification` ⇒ 用户可见路径必有合法题；模型 repair 上限 **1 次**；之后本地 fallback。
2. **禁止换模型 failover**（gateway 无此链路；task 路由是用户配置不是后备）。
3. **禁止「重试 N 次失败 → 直接 advance」**；advance 只由 sufficiency + 字段规则决定。
4. 同阶段连续 follow-up ≥ N 或复读题 → 走既有 complete/字段强制推进，防死循环。
5. 用户可见错误不再包含「Agent 必须返回当前阶段的追问」。

### 2.4 与 complete / start / restart 的对齐

| 入口 | 现状 | B 后 |
|------|------|------|
| `start` / `restart` | 强制 collecting_goals + learningGoals 题 | 保留；题来自模型或 fallback；无 decision 校验 |
| `complete_with_ai` | 服务端强制 advance + 必填总结 | 保留；模型只填 brief + 可选下一题；迁移仍服务端写死 |
| `answer_question` | 读模型 decision | **改为 §2.3 决策表** |

---

## 3. 实施计划

### 3.0 原则

- 分 PR，可独立回滚；先止血后换协议。
- 兼容期双读，避免存量会话与灰度模型裂开。
- 单测 mock 新旧两种协议，直到旧读路径删除。
- 不改 `/course-design/turn` 对话式旧 API 的行为（除非发现共享 normalize 被破坏）。

### 4.1 PR-0：止血（可先于 B 全量，低风险）

**目的：** 消除线上 422，不依赖新字段。

| 文件 | 改动 |
|------|------|
| `backend/services/course_design.py` | `_answer`：同阶段 `next_question` 为空 → 1 次 repair（见 PR-1 prompt 可共用）→ 仍空 → `_fallback_question(stage, topic)`；**删除** :332 的 raise |
| `backend/tests/test_course_design_state_machine.py` | 新增：ask_follow_up + null → 不 422，state 不变，题 id 为 fallback 或 repair 题 |

可选同 PR：`prompts.py` 为 `evaluate_intake_answer` 增加「needs_follow_up 时 nextQuestion 必须非空」硬句（不改字段名）。

**验收：** 现有测试全绿；新测试覆盖同阶段缺题。

### 4.2 PR-1：协议与 prompt（B 形状）

| 文件 | 改动 |
|------|------|
| `backend/agents/schemas.py` | `CourseIntakeStateResult`：新增 `sufficiency`、`clarificationQuestion`、`nextStageQuestion`（alias 对齐 JSON）；`decision`、`next_question` 标 deprecated 或 optional 兼容 |
| `backend/agents/prompts.py` | `COURSE_INTAKE_STATE_SYSTEM`：写死 iff：`needs_clarification ⇔ clarificationQuestion` 非空且合法；`sufficient` 时禁止依赖模型决定 nextStage；保留 briefPatch/topic/阶段约束 |
| `backend/agents/course_intake_agent.py` | `normalize_state_result`：双读——新字段优先；否则旧 `decision`/`nextQuestion` 映射为 `sufficiency`+题；补齐题 stage/target/id 的既有 normalize |

**映射规则（兼容）：**

| 旧响应 | 映射 |
|--------|------|
| `decision.type=ask_follow_up` + 有题 | `sufficiency=needs_clarification`，题=nextQuestion |
| `decision.type=ask_follow_up` + 无题 | `needs_clarification`，题=null（交 PR-0/2 兜底） |
| `decision.type=advance` + nextStage | `sufficient`；题可作为 nextStageQuestion 草稿 |
| 无 decision | 维持现 normalize 默认，再按上表二次映射 |

### 4.3 PR-2：服务端决策表（权威切换）

| 文件 | 改动 |
|------|------|
| `backend/services/course_design.py` | `_answer` 重写为 §2.3；`_missing_transition_summary`/`_repair_transition_result` 扩展为「缺题 repair」与「缺字段 repair」；引入 follow-up 计数（可存 `session.operation` 或新 JSON 列，优先不加迁移则用 `operation`） |
| 同文件 | `complete_with_ai`、`start`/`restart` 与新 normalize 对齐；确认 reviewing_brief 清题逻辑不变 |
| 删除 | :330-332 同阶段 raise（若 PR-0 已删则本 PR 只保留决策表） |

**迁移/兼容：**

- DB：优先**不加列**，follow-up 计数放 `operation_json`；若需持久更干净可后续加列。
- 存量 session：无 decision 字段存储，只存 `current_question`/`brief`/`state`，双读只影响**在线模型响应**，不需数据迁移。
- 回滚：PR-2 可单独 revert 到「读 decision」实现（PR-1 双读仍在则更稳）。

### 4.4 PR-3：测试切换与清理

| 文件 | 改动 |
|------|------|
| `backend/tests/test_course_intake.py` | 夹具改为新字段；保留一组旧 decision 形状测双读 |
| `backend/tests/test_course_design_state_machine.py` | 决策表全分支（见 §5） |
| 清理 | 确认无调用后：文档/注释去掉对模型 `nextStage` 终审的描述；**不删** normalize 旧读，直到观察期结束（可另开 PR-4） |

### 4.5 PR-4（观察期后，可选）：删除旧 decision 读路径

- 移除 `decision` 字段与映射
- prompt/schema 只保留 B
- 全量夹具只测新协议

---

## 4. 分 PR 摘要

| PR | 内容 | 风险 | 可先发 |
|----|------|------|--------|
| **PR-0** | 同阶段缺题 repair1 + fallback，去 422 | 低 | **是（止血）** |
| PR-1 | schema + prompt + normalize 双读 | 中 | 依赖观察 |
| PR-2 | `_answer` 决策表，迁移权单出口 | 中高 | 依赖 PR-1 |
| PR-3 | 测试全量切换 | 低 | 随 PR-2 |
| PR-4 | 删旧协议 | 低 | 观察期后 |

---

## 5. 测试计划

1. `needs_clarification` + 题 → stay，题入库。
2. `needs_clarification` + null → repair 成功 → 用模型题。
3. `needs_clarification` + repair 仍 null / repair 异常 → `_fallback_question`，state 不变，**非 422**。
4. `sufficient` + 字段齐 → advance 到合法下一阶段；题=草稿或 fallback。
5. `sufficient` + 缺 learningOutcome（或 priorKnowledge）→ repair 一次；仍缺 → stay+题，不 advance、不 422「必须返回总结」以外的协议洞。
6. 同阶段连续 needs_clarification ≥2 且字段已齐 → 服务端强制 advance（防循环）。
7. 复读题 → 既有 complete 路径（保持 `test_repeated_follow_up_*`）。
8. 旧 decision JSON 双读映射正确。
9. 字段白名单 / topic 不可改 / go_back / restart 回归。
10. 用户可见错误文案集合中**不再出现**「Agent 必须返回当前阶段的追问」。

---

## 6. 可观测与验收

| 项 | 手段 |
|----|------|
| 协议失败率 | `ai_task_usage` 中 `task=course_intake_state` 的 `succeeded` |
| repair 次数 | 日志或 usage 中 evaluate 后短窗口内第二次 state 调用 |
| 线上 422 | 检索「必须返回当前阶段的追问」「课程需求 Agent 返回结构无效」 |
| 防循环 | follow-up 计数或复读触发 complete 补全时写入服务日志 |
| 发布 | PR-0 可独立 prod；PR-1/2 建议同版本窗口灰度同一环境，避免新旧 prompt 与决策表长期分裂 |

---

## 7. 明确不做（本期）

- 失败后**换模型** failover（无 gateway 基础设施；统计与路由会乱）。
- 「模型连续失败 N 次 → 直接进入下一阶段」。
- 改写 `/course-design/turn` 旧对话协议。
- 前端 UI 结构变更（仍消费 `currentQuestion` 快照，API 形状不变）。

---

## 8. 实施决定

实施时已采用以下决定：

1. 采用 `sufficiency` / `clarificationQuestion` / `nextStageQuestion`，Python 字段继续使用 snake_case + JSON alias。
2. 防循环阈值 N=2；达到阈值后调用一次 complete 补摘要，摘要仍不完整则留在原阶段，不按次数硬推进。
3. follow-up 计数以 `_intakeFollowUpStage` / `_intakeFollowUpCount` 暂存 `operation_json`，推进、返回或重启时清空，不新增迁移。
4. 本次按完整 B 方案一次落地，包含 PR-0 的缺题 repair + fallback 止血。

### 8.1 实施结果

- 新协议已接入；旧 `decision` / `nextQuestion` 仍由 normalize 双读，但服务端不再读取模型 decision 决定迁移。
- start / restart / answer / complete 均由服务端决定合法阶段并为缺失问题提供 fallback。
- 阶段推进要求摘要非空，并且至少有结构化选项或用户自定义详情；纯自定义回答不会被误判为空。
- Mock provider 已切换为新协议，保留专门的旧协议兼容测试。
- 后端全量 210 项测试通过；定向 intake/state-machine 56 项测试通过。

---

## 9. 关键代码索引

| 主题 | 位置 |
|------|------|
| 原 422 抛出点（已删除） | `backend/services/course_design.py` 的 `_answer` 缺题分支 |
| `_answer` 全流程 | `backend/services/course_design.py` |
| 命令分发 | `backend/services/course_design.py` 的 `execute` |
| ALLOWED_ACTIONS / `_fallback_question` | `backend/services/course_design.py` |
| 跨阶段缺题 fallback | commit `400e307` |
| 复读/追问上限 → complete | `backend/services/course_design.py` 的 `_answer` |
| `normalize_state_result` / repair | `backend/agents/course_intake_agent.py` |
| Schema | `backend/agents/schemas.py` 的 `CourseIntakeStateResult` |
| Prompt | `backend/agents/prompts.py` 的 `COURSE_INTAKE_STATE_SYSTEM` |
| Gateway structured | `backend/ai/gateway.py:44-59` |
| 前端命令 | `frontend/src/stores/course-design.ts:139-176` |
| 状态机测试 | `backend/tests/test_course_design_state_machine.py` |
| Intake 协议测试 | `backend/tests/test_course_intake.py` |
