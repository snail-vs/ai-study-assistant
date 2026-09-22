# 模型路由与生成成本控制实施计划

创建时间：2026-09-22 11:35（Asia/Shanghai）

## 目标

让课程生成链路中的每类 AI 任务都可独立配置模型，并建立可验证的调用用量记录，从而把高质量模型集中用于规划、正文与修复，把低成本模型用于摘要等低风险任务。

本计划分两个独立实施会话。每个会话只完成一个阶段、运行该阶段必要的测试、提交代码后停止，减少重复读取上下文和无关全量测试造成的 Codex 5h 用量。

注意：这里优化的是 StudyCenter 自身调用模型的成本与延迟。分会话、缩小读取范围和测试范围，才是降低 Codex 5h 消耗的措施；新建会话不会重置 5h 配额。

## 已知基线

- 课程连续生成、逐节持久化、全局审查和定点修复已经落地：
  - `d174ab4 feat: preserve continuous course generation context`
  - `8a1d061 feat: persist recoverable course generation progress`
  - `016a120 feat: add course-wide quality review and repair`
- `AIGateway` 已按 task 查找 provider，但未登记的 task 会回退默认 provider。
- 新增的 `section_summary`、`course_review`、`course_targeted_repair` 尚未进入完整的任务注册和前端模型角色配置，因此目前不能可靠地单独路由。
- 工作区现有 `docs/教学引导模式.md` 修改属于用户，不得修改或提交。

## 范围边界

本轮只实施模型路由完整性和用量可观测性。

不包含：

- Section Content Blocks 重构；
- mastery evidence 学习闭环；
- CourseStrategy；
- 供应商价格表或金额换算；
- 自动选择“最便宜模型”；
- 合并 review 与 summary 调用（必须先有评测基线再决定）。

## P0：路由完整性与角色配置

### 交付内容

1. 在后端任务注册表中登记：
   - `section_summary`
   - `course_review`
   - `course_targeted_repair`
2. 检查并补齐任务能力分类、provider settings 的校验和序列化，使这三个 task 不再被静默丢弃或只能回退默认 provider。
3. 在前端模型设置中展示并允许配置三类角色：
   - 课程创作：outline、plan、section content、section repair、targeted repair；
   - 质量审查：section review、course review；
   - 快速辅助：section summary 以及已有低风险辅助任务。
4. 保持现有配置兼容：没有为新 task 配置 provider 时继续使用当前默认回退，不要求数据库迁移或用户立即补配置。
5. 增加后端和前端针对性测试，覆盖任务可见、保存后不丢失、角色映射正确、旧配置仍可加载。

### 验收标准

- 三个新增 task 均存在于唯一任务目录中；后端保存/读取路由不会过滤它们。
- 设置页能明确看到它们归属的模型角色。
- 可以给 `section_summary` 和 `course_review` 指定不同 provider/model。
- 未配置新 task 的老用户行为不变。
- 只运行与 AI task/provider settings 和设置页相关的定向测试；全部通过。
- 更新本文“执行记录”，提交一个独立 commit，然后停止，不进入 P1。

### 建议提交信息

`feat: complete course generation model routing`

## P1：任务级用量可观测性

### 设计原则

- 先记录事实，再做成本策略；不硬编码会过时的模型价格。
- token 数据允许为空：供应商不返回 usage 时仍记录调用次数、耗时、结果状态。
- 记录失败调用，但不得保存 prompt、生成正文、密钥或其他敏感内容。
- 课程生成主流程不能因用量记录失败而失败。

### 交付内容

1. 调查当前各 provider 响应中可获得的 usage/model 信息，设计统一的可选 usage 结构。
2. 在统一 AI 调用边界记录至少：
   - task；
   - provider 与实际 model；
   - 成功/失败；
   - duration；
   - input/output/total tokens（可得时）；
   - timestamp；
   - 可安全取得时的业务关联标识。
3. 建立最小持久化与查询能力，支持按时间范围、task、provider/model 汇总调用次数、成功率、耗时与 token；不存原始提示词/响应。
4. 在现有模型设置或管理界面提供一个轻量用量摘要，使用户能比较 `section_content`、`section_review`、`section_summary`、`course_review` 的消耗。
5. 对不返回 token usage、调用失败、记录写入失败以及历史数据为空的情况增加测试。
6. 用固定测试数据证明 task 路由与聚合统计正确；最后运行受影响后端全量测试、前端测试和 typecheck。

### 验收标准

- 每次统一网关调用都能产生不含正文的任务级记录；usage 缺失不会破坏调用。
- 能回答“某段时间哪个 task 调用最多、token 最多、失败最多”。
- 可以依据数据验证把 summary 路由至低成本模型是否真正降低高成本模型调用占比。
- 数据记录故障不影响课程生成结果。
- 数据库迁移可从空库执行；相关定向测试和最终全量测试通过。
- 更新本文“执行记录”，提交一个独立 commit，然后停止。

### 建议提交信息

`feat: track ai task usage`

## 会话交接方式

代码、本文和 Git commit 是跨会话上下文；不依赖聊天记录。新会话不需要复述整个讨论，只需给出下面的提示词。

### 新会话一：执行 P0

```text
在 /data/code/studycenter 执行 .plan/model-routing-cost-control-20260922113543.md 的 P0。
先读仓库 AGENTS.md、该计划和 git log -4；遵守 CodeGraph 规则。只做 P0，运行定向测试，更新计划执行记录，提交代码后停止。不要进入 P1，不要提交用户现有的 docs/教学引导模式.md 修改。
```

### 新会话二：执行 P1

```text
在 /data/code/studycenter 执行 .plan/model-routing-cost-control-20260922113543.md 的 P1。
先读仓库 AGENTS.md、该计划和 git log -5，确认 P0 已在执行记录中完成；遵守 CodeGraph 规则。只做 P1，完成迁移与测试，更新计划执行记录，提交代码后停止。不要提交用户现有的 docs/教学引导模式.md 修改。
```

## 每阶段节省 Codex 用量的约束

- 只读取计划点名的相关模块；定位代码先用 CodeGraph。
- 不重复审查前三个已提交重构阶段，除非测试证明存在回归。
- P0 不跑无关全量测试；P1 收口时才跑最终全量测试。
- 遇到失败先运行最小失败用例，不反复执行整个测试集。
- 每个阶段只做一次实现审查和一次提交；提交后立即结束该会话。
- 任何新需求写入后续计划，不在当前阶段顺手扩 scope。

## 执行记录

- [x] 2026-09-22：计划创建。
- [ ] P0：路由完整性与角色配置。
- [ ] P1：任务级用量可观测性。

