# 首页学习空间 / 知识卡列表切换方案

## 目标

首页支持在两种视图间切换：

- 知识卡视图：保持当前行为，展示一个学习空间下的 root/related 知识卡。
- 学习空间视图：每个 `LearningSpace` 只展示一行，显示课程标题、生成状态、知识卡数量和最近创建时间。

## 当前数据与代码基础

- `GET /learning-spaces` 已返回学习空间列表、生成状态和 `rootCardId`，不需要新增后端接口。
- `learningStore.loadHistory()` 已同时加载空间列表和每个空间的 `/cards`，已有数据足够生成两种视图。
- 当前首页通过 `homeCards = history.flatMap(...)` 生成知识卡列表。
- 已完成空间通过 `rootCardId` 打开根知识卡；失败空间通过 `editingFailedSpace` 进入重编辑。

## 前端改动

### `frontend/src/App.vue`

1. 增加首页视图状态：`cards | spaces`，使用 `localStorage` 保存用户选择，默认保持当前的知识卡视图，避免已有用户界面突然变化。
2. 在“我的知识卡”标题旁增加切换控件：`知识卡` / `学习空间`。
3. 增加 `spaceSummaries` 计算数据：
   - 从 `history` 映射空间；
   - 使用 `historyCards[space.id]` 计算知识卡数量；
   - 生成状态显示 queued/running/failed/completed；
   - completed 且有 `rootCardId` 时支持打开学习空间；
   - failed 时保留“重新编辑”和已实现的“删除”。
4. 模板按视图条件渲染：
   - cards 视图沿用现有 `homeCards` 和知识卡删除逻辑；
   - spaces 视图只显示空间行，点击后打开根知识卡，不直接删除知识卡。
5. 增加空状态和不可打开状态：失败/生成中空间不应调用 `openHistory`，避免请求空的 `rootCardId`。

### 类型与状态位置

第一期可以把视图偏好留在 `App.vue`，因为它只是首页展示偏好，不属于学习运行态；如果后续多个页面都需要该模式，再提取到 `learningStore`。

## 后端改动

第一期不需要后端或数据库改动。两个视图只是同一份 `LearningSpace` + `KnowledgeCard` 数据的不同投影。

## 测试

- 新增/扩展首页组件测试：切换按钮、空间行数量、失败空间操作、完成空间打开根卡。
- 扩展 learning store 测试：空间列表与卡片缓存可同时支撑两种视图。
- 回归已有知识卡删除和失败课程删除测试。
- 运行前端 typecheck、单测和构建；后端仅需确认现有学习空间接口契约未受影响。

## 后续可选增强

- 学习空间行展开显示其下知识卡，而不是直接进入根卡。
- 服务端返回 `cardCount`，避免每个空间分别请求 `/cards`。
- 支持已完成学习空间整体删除；这与当前知识卡软删除是不同的数据删除语义，应单独设计级联清理策略。
