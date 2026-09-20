# 课程生成失败记录删除实施计划

## 当前实现结论

- 失败课程展示在 `frontend/src/App.vue` 的生成中/失败列表中。
- 失败课程已有“重新编辑”入口：课程设计会话通过 `learningSpaceId` 复用原 `LearningSpace`，提交后调用已有的重试生成接口。
- 后端已有 `PUT /learning-spaces/{space_id}/generation`，但没有删除 `LearningSpace` 的接口。
- 现有 `DELETE /cards/{card_id}` 只把知识卡标记为 `deleted`，不会删除学习空间。
- 数据库外键默认没有 `ON DELETE CASCADE`，并且 SQLite 开启了外键约束；直接删除学习空间可能被 `CourseDesignSession`、`KnowledgeCard`、`LearningRuntime` 等引用阻止。

## 删除对象的确定

需要区分两类首页记录：

- 已完成记录：页面展示的是知识卡，现有删除按钮调用 `DELETE /cards/{card_id}`，实际是知识卡软删除；学习空间仍然保留，讨论、消息、笔记和学习分支也保留。
- 生成失败记录：页面展示的是学习空间的生成状态，此时通常还没有知识卡，因此删除失败记录必须删除 `LearningSpace`（以及关联的课程设计会话），不能调用知识卡删除接口。

本次“生成失败后重新编辑，现在增加删除”对应第二类，删除对象确定为学习空间，不是知识卡。

## 建议的第一期范围

只支持删除“生成失败且尚未产生根知识卡”的课程记录。原因是当前需求紧跟失败课程列表，且这条路径数据边界清晰，不会误删已投入使用的课程内容。

### 后端

1. 在 `backend/learning_space_api.py` 增加：
   - `DELETE /learning-spaces/{space_id}`
   - 通过 `owned_space` 校验当前用户归属。
   - 仅允许 `generation_status == "failed"` 且 `root_card_id is None`；其他状态返回 `409`，避免删除排队中/运行中的任务或已完成课程。
   - 删除该空间关联的 `CourseDesignSession`，再删除 `LearningSpace`，事务提交后返回已删除状态和 `spaceId`。
2. 在 `backend/tests/test_learning_space_api_contract.py` 更新路由契约。
3. 增加行为测试：归属校验、失败记录可删、排队/运行/已完成拒绝、关联设计会话一并删除、重复删除行为。

### 前端

1. 在 `frontend/src/App.vue` 的失败生成条目旁增加“删除”按钮，并阻止点击冒泡。
2. 删除前显示确认文案，明确只删除失败课程记录和编辑草稿。
3. 调用 `DELETE /learning-spaces/{space_id}`；成功后从 `learningStore.history` 移除该空间，并清理 `historyCards` 对应项；若当前正在编辑该条记录，同时退出编辑状态并重置课程设计 store。
4. 在 `frontend/src/stores/learning.ts` 增加集中化的 `removeHistoryItem` 或 `deleteLearningSpace`，避免 App 直接维护多处列表状态。
5. 增加 store/component 测试，覆盖成功删除、取消删除、接口失败和删除当前编辑项。

## 数据删除方式

第一期采用“失败记录硬删除”：

1. 校验空间属于当前用户，且状态为 `failed`、没有 `root_card_id`。
2. 删除 `course_design_sessions.source_learning_space_id = space_id` 的设计会话；这是失败课程重新编辑链路留下的引用。
3. 删除 `learning_spaces` 记录。
4. 整个操作放在同一事务中，任一步失败则回滚。

失败生成正常情况下不会创建 `KnowledgeCard`、章节、活动、会话或笔记，因此不需要删除这些内容。实现时仍应在服务层检查是否存在卡片；若存在则返回 `409`，避免误删已生成内容。

## 后续若要支持删除已完成课程

不能复用第一期的简单删除，需要单独设计“删除课程/学习空间”策略。当前依赖链包括：

`LearningSpace → KnowledgeCard → CardSection / Conversation / Note / Activity / Guidance / Proposal / BridgeNote`，以及 `Conversation → Message / AIRun`、`Activity → ActivityAttempt`、`LearningSpace → LearningRuntime → LearningRuntimeRecord`。

建议后续采用专门的删除服务，按子表依赖顺序显式删除并加集成测试；不要只依赖 ORM relationship cascade，因为多个模型目前没有完整关系定义，也没有数据库级级联。若产品需要可恢复，则改成给 `LearningSpace` 增加软删除字段并让所有列表/读取接口过滤，而不是物理删除。

## 并发与任务安全

- 第一期开启删除的状态限制，避免删除 `queued`/`running` 时后台 worker 之后又写回结果。
- 若未来必须允许删除进行中的任务，需要增加 `cancelled` 状态、worker 的取消检查以及 lease/token 失效逻辑，不能只删除数据库行。

## 验证

- 后端：路由契约、删除行为、外键约束下的事务测试。
- 前端：store 与失败列表组件测试。
- 运行后端测试、前端单测和前端构建。
