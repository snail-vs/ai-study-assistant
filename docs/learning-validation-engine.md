# 学习验证引擎：架构设计与渐进接入方案

本文是针对 StudyCenter 当前代码的设计方案。目标是在不破坏现有“理解检查”闭环的前提下，把 Quiz 专用实现逐步演进成可组合的学习验证引擎，覆盖理论理解、数学推理、编程实践、绘画作品和实验记录等学习活动。

本方案与 `plan.md`、`docs/learning-activities.md` 保持一致：本轮只定义结构和接入路线，不修改数据库、业务 API 或前端代码。

## 1. 产品定位

学习验证引擎回答的不是“用户答对了几道题”，而是：

> 学习者是否获得了本章节声明的能力，依据是什么，下一步最小的学习动作是什么？

它和课程正文、知识卡的边界如下：

| 模块 | 负责的问题 |
| --- | --- |
| 知识卡/章节 | 学什么、按什么顺序学 |
| 学习活动 | 要证明什么能力、提交什么证据 |
| 验证引擎 | 如何生成任务、评价证据、定位薄弱点 |
| 导师/知识分支 | 如何把评价结果转成下一步学习建议 |

现有的“理解检查”是引擎的第一种活动形态：挂在章节上的、包含单选/判断/简答的 `quiz`。新引擎不是另起一个并行产品，而是保留它的入口和数据兼容性，并逐步把“题目”提升为“验证任务”。

### 1.1 与费曼学习法、检索和迁移的关系

推荐把一次验证路径设计成递进的证据链，而不是把所有题型都混在一起：

1. **识别/检索**：选择、判断、配对、排序，验证能否从记忆中取出和辨认关键概念。
2. **解释/费曼式表达**：用自己的话解释概念、因果链、例子或反例，验证是否能重建心智模型，而非只认得答案。
3. **应用**：解题、写代码、画草图、执行实验步骤，验证是否能把知识用于任务。
4. **迁移/反思**：修改条件、改错、比较方案、解释异常结果，验证能否处理新情境并评估自己的过程。

因此“选择题 → 简短解释 → AI 针对薄弱点追问一题”是适合当前产品的第一条路径，但不是所有课程都必须走完整路径。系统根据学习目标和证据类型组装最小有效路径：概念章节优先解释，编程优先运行测试，绘画优先作品 rubric，实验优先过程和数据证据。

选择题和解释题并不重复：前者主要测检索/识别，后者测生成性理解。两者若连续出现，界面应明确标记为“快速检查”和“用自己的话解释”，并在结果页把它们合并为同一能力目标的不同证据，而不是显示两个相互竞争的分数。

### 1.2 产品原则

- 以“学习目标、能力层级、证据、评价方式、反馈动作”抽象，不按学科硬编码整套流程。
- 任务生成可以使用 AI，但任务规格、评分点、状态转换和安全门槛由系统控制。
- 确定性证据优先由确定性 evaluator 判定；AI 负责受约束的语义评价、诊断和追问。
- 每次追问只针对一个最重要的缺失证据，默认最多一次；它是当前尝试的子步骤，不是无限聊天。
- 低置信度时不输出强结论，不自动制造前置知识分支。
- 总分继续兼容现有接口，但新数据同时保存按目标/rubric 的掌握证据。

## 2. 统一领域模型

建议把引擎的最小领域对象定义为：

```text
AssessmentSpec       一次活动的版本化验证规格
  ├─ learningGoals   要验证的目标和能力层级
  ├─ tasks           基础任务列表
  ├─ policies        评价、追问、通过和安全策略
  └─ version         规格/契约版本

TaskSpec             一个可作答任务
  ├─ prompt          给学习者看的任务
  ├─ evidenceSpec    需要提交的证据和回答组件
  ├─ evaluationSpec  如何判定证据
  └─ followUpSpec    允许如何派生追问

Evidence             学习者提交的回答、代码、图片、文件、步骤或数据
Evaluation           evaluator 的可审计结果（分数、rubric、置信度、证据）
Diagnosis             目标级薄弱点、错误类型和建议动作
Intervention         提示、追问、重试、复习、导师反馈或人工审核
Attempt              一次活动尝试；保存基础任务及派生追问的全过程
```

### 2.1 能力、知识和证据维度

不要把 `content_type` 直接当作题型。章节已有 `content_type`（`concept | practice | summary | quiz | interactive`），它描述内容/章节呈现；引擎另用以下稳定维度：

| 维度 | 推荐值/示例 | 说明 |
| --- | --- | --- |
| `capability` | `recognize`, `recall`, `explain`, `apply`, `transfer`, `reflect` | 要验证的动作，不是学科名称 |
| `knowledgeKind` | `fact`, `concept`, `mechanism`, `procedure`, `strategy`, `skill` | 被验证的知识形态 |
| `evidenceKind` | `choice`, `text`, `ordered_items`, `steps`, `code`, `image`, `file`, `measurement`, `audio` | 学习者提交什么证据 |
| `renderer` | `choice`, `textarea`, `sort`, `step_editor`, `code_editor`, `canvas`, `upload`, `table` | 前端如何收集证据 |
| `evaluator` | `deterministic`, `rubric`, `code_tests`, `vision_rubric`, `human_review` | 谁/什么评价证据 |
| `errorType` | `missing_concept`, `wrong_order`, `unsupported_claim`, `procedure_error`, `result_error`, `safety_violation` | 诊断结果的受控分类 |

`capability` 和 `evidenceKind` 应是引擎的主要扩展点；新增绘画或实验不应新增一套完全不同的尝试模型。

## 3. 建议的结构化规格

以下示例是公开规格的概念结构，不要求第一阶段立刻增加同名 Python 类或数据库表。首阶段可以作为 `LearningActivity.content_json` 的 `assessmentSpec`；答案、隐藏 rubric 细节、参考答案和测试用例必须拆到 `answer_key_json` 中以相同 task ID 关联。公开规格只声明 evaluator 类型及作答约束。

```json
{
  "specVersion": 2,
  "activityType": "quiz",
  "title": "理解检查：函数调用栈",
  "objective": "能够说明嵌套调用时栈帧的创建、返回和生命周期",
  "learningGoals": [
    {
      "id": "goal-stack-lifecycle",
      "statement": "解释 A 调用 B、B 调用 C 时的栈帧变化",
      "capability": "explain",
      "knowledgeKind": "mechanism",
      "masteryWeight": 1.0
    }
  ],
  "tasks": [
    {
      "id": "t-order",
      "kind": "single_choice",
      "capability": "recognize",
      "prompt": "三个栈帧的创建顺序是什么？",
      "evidence": {"kind": "choice", "renderer": "choice", "required": true},
      "evaluation": {
        "kind": "deterministic",
        "points": 20
      },
      "followUp": {"eligibleWhen": ["wrong_order"], "maxGenerated": 1}
    },
    {
      "id": "t-explain",
      "kind": "short_answer",
      "capability": "explain",
      "prompt": "请用 2–4 句话解释 C 返回后回到哪里，以及为什么不能依赖 B 的局部变量存储位置。",
      "evidence": {
        "kind": "text",
        "renderer": "textarea",
        "required": true,
        "constraints": {"minChars": 10, "maxChars": 1200}
      },
      "evaluation": {
        "kind": "rubric",
        "rubric": [
          {"id": "return-target", "label": "返回位置", "weight": 0.4},
          {"id": "frame-lifetime", "label": "栈帧生命周期", "weight": 0.4},
          {"id": "causal-language", "label": "因果表达", "weight": 0.2}
        ],
        "threshold": 60,
        "confidenceRequired": 0.7
      },
      "followUp": {
        "eligibleWhen": ["missing_rubric", "ambiguous_claim"],
        "maxGenerated": 1,
        "target": "first_missing_rubric"
      }
    }
  ],
  "policies": {
    "maxFollowUps": 1,
    "masteryThresholds": {"mastered": 85, "developing": 60},
    "lowConfidenceAction": "review_and_no_branch",
    "retainAnswerKeyServerSide": true
  }
}
```

对应的私有评分规格仅由后端读取，例如：

```json
{
  "specVersion": 2,
  "tasks": {
    "t-order": {
      "answer": "a-b-c",
      "feedback": {"correct": "顺序正确。", "incorrect": "调用者先存在，被调用者随后入栈。"}
    },
    "t-explain": {
      "rubric": [
        {"id": "return-target", "description": "指出 C 返回后回到 B 中调用 C 后的下一条指令"},
        {"id": "frame-lifetime", "description": "说明 B 结束后栈帧或局部存储位置失效、可被复用"},
        {"id": "causal-language", "description": "把调用、返回和生命周期的因果关系说清楚"}
      ],
      "referenceAnswer": "..."
    }
  }
}
```

### 3.1 对象职责和安全边界

- `AssessmentSpec`：可版本化、可审查、可重放的活动蓝图。不能包含用户本次回答。
- `TaskSpec`：稳定的任务 ID、题面和证据要求。追问任务要带 `parentTaskId`，但不改变基础任务 ID。
- `EvidenceSpec`：只描述允许的回答载体、大小/长度/格式和是否必填，不接受任意前端组件名。
- `EvaluationSpec`：描述 evaluator 类型和可公开的规则；答案键、隐藏测试、参考解答和内部 prompt 仍是服务端私有数据。
- `Evaluation`：包括 `score`、`correct`/`status`、`rubricItems`、`confidence`、`evidenceRefs`、`feedback` 和 `errorType`。AI 原始输出应记录在受控日志或脱敏审计存储，而非直接下发。
- `Diagnosis`：面向教学的结果，如 `missing_rubric`、`wrong_order`、`procedure_error`，不能把模型猜测写成确定事实。
- `FollowUpSpec`：限制触发条件、最多次数、目标证据和可用 renderer；生成的追问需要经过 schema 校验和敏感内容检查。

## 4. 生成、作答、评价和追问状态机

一次基础活动和一次尝试应按以下状态约束运行：

```text
活动：draft → generating → ready → archived/failed
尝试：created → answering → submitted → evaluating → evaluated
                                      └─ evaluation_failed → reviewable
评价后：evaluated → follow_up_pending → follow_up_answering
                              └────────→ completed
追问后：follow_up_answering → follow_up_evaluating → completed
```

推荐的运行步骤：

1. **生成**：根据章节目标和正文请求 AI 输出结构化 `AssessmentSpec`；系统验证目标覆盖、题面长度、答案键一致性、禁止超纲和任务数量。失败时活动为 `failed`，不保存半成品。
2. **发布**：活动查询只返回公开题面、证据要求和渲染信息，不返回答案键、隐藏 rubric 参考答案或隐藏测试。
3. **作答**：前端按 `renderer` 注册表渲染，提交带 `taskId` 的 evidence。服务端重新校验活动版本、证据大小/类型和必答项，不信任客户端分数。
4. **评价**：编排器按 evaluator 注册表执行；可以先确定性判分，再调用 AI rubric 或诊断。结果应保留每个目标和 rubric 项，而不只是总分。
5. **诊断**：按“第一个可行动的认知断点”生成 `Diagnosis`。只有明确影响当前章节的误区，才交给现有知识断层诊断；单题错误不自动建分支。
6. **追问决策**：若结论正确且证据完整，完成尝试或进入迁移；若结论对但缺 rubric，生成一个最小追问；若低置信度，给出“待确认/建议复习”，不强制追问或建分支。
7. **一次追问**：在同一 `ActivityAttempt` 下保存 `parentTaskId`、派生任务、回答和评价。默认最多 1 次，追问只覆盖首个缺失证据，完成后重新汇总目标级掌握度。
8. **反馈**：返回逐任务反馈、诊断摘要、下一步动作和可选导师反馈。追问结果不应创建第二条 `LearningActivity`。

建议的追问策略：

| 评价现象 | 诊断 | 一次追问示例 |
| --- | --- | --- |
| 结论和理由都完整 | `mastered` | 提供一个变式，验证迁移（可选） |
| 结论正确、理由缺环节 | `missing_rubric` | “请补充 C 返回后具体从 B 的哪条指令继续。” |
| 结论错误但能定位步骤 | `procedure_error` | “在第几步开始偏离？请重新排序这三帧。” |
| 表述含糊、AI 低置信度 | `ambiguous_claim` | 要求举一个具体输入/结果，不作强判定 |
| 完全不会或违反安全要求 | `needs_scaffold`/`safety_violation` | 降阶题或停止操作，转人工/安全提示 |

## 5. 题型、Renderer 和 Evaluator 注册机制

题型、呈现组件和评价器需要解耦。推荐三个白名单注册表，而不是在 `App.vue` 或 API 里累积 `if/else`：

```text
TaskKindRegistry
  single_choice → evidence: choice → renderer: choice → evaluator: deterministic
  true_false    → evidence: choice → renderer: choice → evaluator: deterministic
  short_answer  → evidence: text   → renderer: textarea → evaluator: rubric
  ordered_items → evidence: ordered_items → renderer: sort → evaluator: deterministic/rubric
  structured_steps → evidence: steps → renderer: step_editor → evaluator: rules/rubric
  code          → evidence: code → renderer: code_editor → evaluator: code_tests
  artwork       → evidence: image → renderer: canvas/upload → evaluator: vision_rubric
  experiment_log→ evidence: measurement/file → renderer: table/upload → evaluator: rules/rubric
```

每个注册项至少需要：

```text
kind
public_schema()              # 下发给前端的安全 schema
validate_evidence(value)     # 大小、格式、必填和领域约束
renderer_key                 # 前端组件白名单键
evaluator_keys               # 允许的 evaluator 白名单
feedback_projection(result)  # 映射为统一 ActivityResult
```

前端可以继续从 `App.vue` 迁移出 `ActivityContainer`，由 `renderer_key` 选择组件；后端可以先在 Python 中使用字典注册，随后再拆成独立模块。注册项不得由 AI 直接指定任意 Python 类、SQL、URL 或 shell 命令。

### 5.1 Evaluator 边界

- **确定性 evaluator**：单选、判断、排序、格式/步骤规则。结果可重复，应是客观题的唯一分数来源。
- **Rubric evaluator**：简答、解释、方案和实验分析。输入限定为章节内容、题面、rubric 和用户证据；输出结构化分项结果、反馈、错误类型和置信度。
- **代码 evaluator**：使用隔离环境、资源限制和固定测试用例；测试结果是代码正确性的主要证据，AI 只解释失败原因或提出下一步。
- **视觉 rubric evaluator**：对画面/作品按明确维度评分，如比例、结构、透视、明暗；必须返回证据区域/理由和置信度，不以一个不可解释的总分替代 rubric。
- **人工 reviewer**：安全敏感、评分分歧大或低置信度的实验/作品进入待审核，而不是让 AI 强行通过。

评价器应返回统一结构，并允许 `status = passed | failed | needs_review | evaluator_error`。网络/模型失败时，客观题仍可完成；AI 题显示待评价并可重试，不应丢失用户答案。

## 6. 跨课程组装示例

### 6.1 理论/概念：调用栈

```text
recognize：排序 A、B、C 栈帧创建顺序（single_choice + deterministic）
explain：解释 C 返回目标和 B 栈帧生命周期（short_answer + rubric）
follow-up：若漏掉“下一条指令”，只追问该环节
transfer：给出递归调用或另一个调用图，让用户画/排序栈帧变化
```

### 6.2 数学

```text
recognize：选择适用公式/方法
explain：说明为什么满足公式前提（text + rubric）
apply：提交答案和中间步骤（structured_steps + rules/rubric）
transfer：改变一个条件，重新计算并解释变化
```

最终答案不能覆盖中间步骤；若结果错误，诊断器应定位第一个错误步骤。

### 6.3 编程

```text
recognize：预测输出或选择复杂度
explain：解释关键分支/调用过程
apply：提交代码（code_editor + sandboxed code_tests）
transfer：修改输入边界或补一个失败测试
```

代码执行必须有超时、CPU/内存、文件系统和网络隔离。AI 不应仅凭代码文本给出“通过”。

### 6.4 绘画

```text
recognize：从示例中指出透视/构图问题
explain：说明某种技法要解决的问题
apply：画布或上传局部练习
reflect：按 rubric 说明自己最需要修改的一处
```

作品评价按比例、结构、透视、明暗、色彩等维度返回可见依据和建议修改区域。优先给“下一笔/下一处练习”，不要只给一个总分；支持修改前后对比。视觉模型不稳定时标记 `needs_review`。

### 6.5 实验

```text
实验前：预测现象、变量和理由（text + rubric）
实验中：记录步骤、控制变量、观测和测量（structured_steps/table/file）
实验后：用数据验证预测并分析误差（rules + rubric）
迁移：改变一个变量，预测结果和安全措施（text + rubric）
```

“结果异常”不等于“未掌握”；应分别评价安全、过程有效性、数据质量、结论和误差分析。实体实验涉及危险操作时，安全检查和教师确认优先于 AI 评分。

## 7. 对现有代码的逐点接入

### 7.1 数据层

当前 `LearningActivity` 位于 `backend/models.py`，包含 `content_json` 和 `answer_key_json`；`ActivityAttempt` 保存 `answers_json`、`result_json`、总分、掌握级别和诊断摘要。第一阶段继续使用这两个 JSON 字段：

```text
content_json = {
  "specVersion": 2,
  "assessmentSpec": { ... },
  "questions": [ ... ]       # 兼容旧前端的投影视图
}
answer_key_json = {
  "specVersion": 2,
  "tasks": { ... }            # 仅服务端读取
}
```

`ActivityAttempt.result_json` 增加兼容字段即可：

```json
{
  "specVersion": 2,
  "items": [],
  "evidence": [{"taskId":"t-explain","kind":"text"}],
  "diagnoses": [],
  "followUp": {"status":"not_needed"},
  "confidence": 0.86
}
```

当前迁移 `backend/migrations/versions/ab45de67f890_add_learning_activities.py` 建立了 `uq_section_activity_type`，即同一章节的同一种 `activity_type` 只能有一条活动。因此首阶段不新建“解释 quiz”或“追问 quiz”：一份活动就是一个版本化验证规格，追问作为同一 `ActivityAttempt` 内的派生 task/step 保存。未来若需要同类活动多个版本，再设计显式 `activity_version` 或模板/实例关系，不直接删除该唯一约束。

### 7.2 Agent 和 schema

- `backend/agents/schemas.py` 当前有 `QuizQuestion`、`QuizAnswerKey`、`QuizDraft`、`ShortAnswerEvaluation`。保留这些模型作为 `specVersion: 1` 兼容结构，新增 `AssessmentSpec`、`LearningGoalSpec`、`TaskSpec`、`EvidenceSpec`、`EvaluationSpec`、`RubricItem`、`EvaluationResult`、`FollowUpDecision` 等结构化模型。
- `backend/agents/assessment_agent.py` 当前 `generate_quiz()` 生成 `QuizDraft`，`evaluate_short_answer()` 评价简答。建议先增加 `generate_assessment_spec()` 和 `evaluate_task()` 的薄适配层，内部仍可复用旧 prompt 和 gateway；等契约稳定后再替换为多 evaluator。
- `backend/agents/prompts.py` 当前生成 prompt 固定要求 4 题（2 道客观、1 道概念辨析、1 道简答），评价 prompt 输出 `score/feedback/misconception`。第一阶段保留固定 Quiz 生成策略，通过适配器包装为 `AssessmentSpec`；后续 prompt 改为“只生成给定目标/证据/评分点”，禁止模型任意扩展题型。

### 7.3 API 和服务边界

`backend/api.py` 当前的活动端点包括：

- `POST /cards/{cardId}/sections/{sectionId}/activities/quiz`：生成或复用每章节唯一的 quiz。
- `GET /activities/{activityId}`、`GET .../attempts/latest`：返回不含答案键的活动和结果。
- `POST /activities/{activityId}/attempts`：当前在一个函数中完成答案解析、客观判分、AI 简答评价、尝试持久化、导师反馈和知识断层诊断。

建议先抽出服务边界，再扩大 schema：

```text
AssessmentGenerationService
AttemptSubmissionService
EvaluationOrchestrator
DiagnosisService
FollowUpPolicy
ActivityResultProjector
```

API 只负责认证、加载用户所属活动、调用服务、映射响应和事务边界。`AttemptSubmissionService` 应保证一次提交幂等/不重复触发外部反馈；`EvaluationOrchestrator` 负责按 task 选择 evaluator；`DiagnosisService` 负责把结果转换成导师反馈和现有 `RelatedCardProposal`。这也是首个编码切片，优先降低当前 `submit_activity_attempt` 的耦合风险。

### 7.4 Pydantic、OpenAPI 和前端

- `backend/schemas.py` 当前公开 `LearningActivityResponse.questions`、`SubmitActivityAttemptRequest.answers` 和 `ActivityResultItem`。兼容期保留这些字段；新增 `specVersion`、`tasks`、`evidenceSchema`、`followUp` 时使用可选字段，并在 OpenAPI 中标注版本。
- `contracts/openapi.yaml` 当前 `LearningActivity` 只描述 Quiz 问题，提交答案是任意 object。第一阶段先补充统一任务/证据/结果的 schemas，同时保留 `questions` 和旧 endpoint；旧客户端仍读取投影视图。
- `frontend/src/App.vue` 当前把 quiz 状态、打开、提交和渲染集中在 `activityAnswers`、`activityResult`、`openQuiz()`、`submitQuiz()` 和模板中。先抽 `ActivityContainer`，再建立 renderer 注册表；短期可由 `tasks` 投影成旧 `questions`，长期改成按 `task.kind`/`renderer` 渲染。
- 当前前端在提交后直接展示结果并调用导师反馈/推荐加载。引擎接入后应增加 `follow_up_pending` 和 `follow_up_answering` 两个 UI 状态，但不必改变章节导航或知识卡主线。

## 8. 兼容、迁移和版本策略

### 8.1 旧 Quiz 适配

定义 `LegacyQuizAdapter`：

```text
QuizQuestion.type → TaskSpec.kind
QuizQuestion.prompt/options → TaskSpec.prompt/evidence
QuizAnswerKey.answer → deterministic evaluator
QuizAnswerKey.rubric/reference_answer → rubric evaluator 私有配置
旧 ActivityAttempt.result.items → EvaluationResult.items
```

旧活动读取时若 `content_json.version` 缺失或为 `1`，运行时转换为内存中的统一 spec，不要求立即回填数据库。新生成活动写入版本号和兼容投影。答案键绝不进入 `LearningActivityResponse`、OpenAPI 公开 schema 或前端状态。

### 8.2 渐进版本

- `specVersion: 1`：当前固定 Quiz，支持 `single_choice | true_false | short_answer`。
- `specVersion: 2`：统一 `AssessmentSpec`、目标/rubric、证据和一次追问；仍可投影为旧 `questions`。
- `specVersion: 3`：排序、步骤、代码、图片、测量等证据；按 renderer/evaluator 白名单扩展。

活动版本和尝试版本必须一并记录。活动重新生成时不要覆盖已经产生的尝试所引用的 spec；可以将旧活动标记归档并在未来引入版本实体。由于当前唯一约束限制同类型活动数量，首阶段的“版本”仅是 JSON 内的规格版本，不是创建第二个活动。

### 8.3 分数兼容

继续计算 `ActivityAttempt.score` 和 `mastery_level`：`mastered >= 85`、`developing >= 60`、否则 `needs_review`。同时保存目标级证据和置信度。新路径若有追问，建议总分保留基础任务的兼容分数，另外在结果中声明 `postFollowUpMastery`，避免历史报表突然改变含义。

## 9. AI 边界、低置信度、安全、成本和可观测性

### 9.1 AI 能做什么、不能做什么

AI 可以：

- 根据章节内容生成受约束的题面、选项和 rubric 草稿；
- 对自然语言解释、开放作品和实验分析做结构化 rubric 评价；
- 把已确定的错误映射为可行动的反馈和一次追问；
- 解释代码测试失败或帮助教师审阅。

AI 不应单独决定：

- 用户身份、权限、活动所有权和答案键访问；
- 客观题正确性、代码是否安全执行、实验安全是否合规；
- 是否自动创建前置知识分支；
- 是否执行任意工具、外部请求或本地命令；
- 在低置信度下给出“已掌握/未掌握”的强结论。

### 9.2 低置信度和失败降级

- schema 校验失败：丢弃模型结果，活动生成失败或重试，不把半结构化文本展示给用户。
- evaluator 超时/服务不可用：保存 evidence，结果为 `needs_review`，客观题先返回可确定部分。
- 置信度低于 evaluator 规定阈值：反馈使用“从回答看可能遗漏……，建议复习/补充”，不建分支、不强制扣除全部分数。
- evaluator 与规则结果冲突：规则结果优先；把冲突记录到审计指标并允许人工复核。
- 用户上传不符合格式或包含恶意内容：在文件解析/视觉调用前拒绝或隔离，不交给 prompt。

### 9.3 安全和隐私

- 所有活动和尝试继续通过当前用户/卡片归属校验；服务端重新读取答案键。
- 文本长度、文件 MIME、大小、图片分辨率、代码执行时间和资源限额都在服务端校验。
- 代码在无网络、临时文件系统、CPU/内存/时间限制的沙箱中运行；禁止把用户代码直接拼进 shell 命令。
- 上传的图片、实验文件和模型日志尽量最小化保存，明确保留期限；脱敏后才进入可观测性系统。
- prompt 注入、用户在答案中要求泄露 rubric/答案键等内容一律视为普通证据，不改变 evaluator 的系统约束。

### 9.4 成本和可观测性

- 基础客观题不调用 AI；简答只在存在简答任务时调用一次 evaluator；追问默认最多一次。
- 规格可缓存，按章节正文/目标/spec 版本生成；重复打开活动不重复生成。
- 记录 `activity_id`、`attempt_id`、`task_id`、spec 版本、evaluator、模型路由、耗时、token/费用、重试次数、状态和置信度，但不记录未脱敏的答案或文件内容。
- 关键指标：生成成功率、schema 拒绝率、各 evaluator 错误率、平均/尾部延迟、AI 调用成本、低置信度率、追问触发率、追问后掌握变化、前置分支误触发率、人工复核率。
- 结果要可重放：保存 prompt/spec 摘要、模型版本和 evaluator 版本；不要依赖当前模型重新计算历史成绩。

## 10. 分阶段实现、测试和验收

### Phase 0：规范落地（当前）

- 确认术语、目标/证据/evaluator/追问边界。
- 产出本设计文档，暂不改业务代码和数据库。

验收：能解释选择题与解释题的互补关系；同一模型可描述理论、数学、编程、绘画和实验；明确首个编码切片。

### Phase 1：兼容式内核

- 增加 `LegacyQuizAdapter` 和统一内存 spec/result 类型。
- 抽取 `AttemptSubmissionService`、`EvaluationOrchestrator` 和 `ActivityResultProjector`，保留现有 endpoint 和响应字段。
- 先注册 `single_choice`、`true_false`、`short_answer` 及 deterministic/rubric 两类 evaluator。
- 不改变 `uq_section_activity_type`，不新增追问活动表。

测试：旧 Quiz 响应快照、答案键不泄露、客观题判分等价、简答 evaluator 失败可重试、事务失败不产生半个 attempt、越权活动访问为 404。

### Phase 2：解释和一次追问

- 在 `result_json` 中增加 rubric 命中/缺失、错误类型、置信度和 `followUpDecision`。
- 增加同一 attempt 内的派生 task/step 保存和提交协议。
- 前端改为 `answering → evaluated → follow_up_answering → completed`。

测试：只追问一次、追问指向首个缺失 rubric、重复提交不重复追问、低置信度不自动建分支、基础分数兼容。

### Phase 3：应用和结构化过程证据

- 增加排序、步骤、表格/测量证据。
- 数学中间步骤、实验记录采用结构化 JSON，并由规则和 AI rubric 组合评价。

测试：非法步骤/缺字段拒绝，首个错误定位，异常实验结果与过程掌握分离。

### Phase 4：代码和作品证据

- 增加代码编辑器、图片/文件上传和相应 renderer/evaluator。
- 代码使用沙箱测试；绘画使用可见 rubric；实验加入安全检查点和人工审核。

测试：沙箱逃逸/超时/资源限制，恶意文件隔离，视觉低置信度降级，安全违规阻断，前后端大文件限制和审计。

### 10.1 首个编码切片（明确推荐）

推荐只做一个后端、兼容式切片：

> 从 `backend/api.py::submit_activity_attempt` 抽出 `AttemptSubmissionService`，引入 `LegacyQuizAdapter` 和统一的内存 `TaskEvaluation` 结果；保持现有三个 endpoint、数据库字段和前端响应不变。

切片边界：

1. `LegacyQuizAdapter` 把 `content_json`/`answer_key_json` 转成统一 task 列表。
2. `EvaluationOrchestrator` 复用现有确定性判分和 `AssessmentAgent.evaluate_short_answer()`，统一返回 `EvaluationResult`。
3. `AttemptSubmissionService` 负责校验、调用 evaluator、计算兼容总分、写入 `ActivityAttempt`。
4. API 层继续负责导师反馈和知识断层诊断，或在同一切片末尾明确移入 `PostAssessmentHook`；不要在本切片同时改新题型和前端。
5. 为服务和适配器增加单元测试、旧接口集成测试；确认行为等价后，再进入 Phase 2 的追问。

这样能先验证最危险的边界——答案键隔离、判分结果稳定、持久化和外部 AI 失败处理——并为后续 renderer/evaluator 扩展提供真实的插入点。

## 11. 结论

学习验证引擎应被实现为“目标驱动的证据和反馈编排器”，而不是更多题型的集合。现有理解检查继续作为第一种活动：选择题提供检索证据，简答提供费曼式解释证据，AI 只在明确缺失证据时进行一次受限追问。数学、编程、绘画和实验只替换证据 renderer、evaluator 和领域 rubric，共享活动、尝试、诊断和干预模型。

首阶段最重要的工程动作是抽离 `submit_activity_attempt` 的服务边界并建立旧 Quiz 适配层；在此基础上，再以结构化追问、步骤/作品证据和领域 evaluator 逐步扩展，而不是一次性重写数据库、API 和前端。
