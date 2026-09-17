是的，这应该是下一层，而且很有必要。

但我建议不要简单做成：

```text
每个 Agent 固定一个模型
```

更通用的做法是：

```text
任务类型 / Agent 角色
        ↓
模型路由策略
        ↓
具体 Provider + Model
```

## 一、为什么需要模型路由

不同环节对模型的要求不同：

| 环节 | 要求 | 推荐模型 |
|---|---|---|
| 课程大纲与知识卡生成 | 理解深度、结构规划、内容完整性 | 强模型 |
| 老师章节引导 | 教学表达、上下文理解 | 中强模型 |
| 旁支问题回答 | 速度、成本、连续对话 | 中等或便宜模型 |
| 知识断层诊断 | 分类、结构化判断 | 便宜模型 |
| 推荐知识卡 | 判断是否需要分支 | 便宜模型 |
| 知识桥接 | 简短总结 | 便宜模型 |
| 章节小测评分 | 准确性和理解判断 | 中强模型 |
| 图片、音频、视频 | 专用模型 | 各自 Provider |

如果所有任务都使用最强模型：

- 成本高
- 旁支响应速度慢
- 简单任务浪费能力
- 高并发能力差

所以你的想法是对的：

> 主 Agent 负责课程生成时使用能力强的模型，旁支 Agent 使用更快、更便宜的模型。

## 二、建议设计成两层路由

### 第一层：任务路由

不要只根据 Agent 名称选择模型，而是根据任务：

```text
knowledge_card_generation
teacher_guidance
side_answer
knowledge_diagnosis
recommendation
bridge_note
assessment
```

例如：

```json
{
  "knowledge_card_generation": {
    "provider": "deepseek",
    "model": "deepseek-reasoner"
  },
  "side_answer": {
    "provider": "deepseek",
    "model": "deepseek-chat"
  },
  "knowledge_diagnosis": {
    "provider": "deepseek",
    "model": "deepseek-chat"
  }
}
```

这是最稳定的基础。

### 第二层：Agent 默认策略

Agent 可以带一个默认模型策略：

```text
Teacher Agent
├── defaultTask: teacher_guidance
├── preferredModel: medium
└── fallbackModel: cheap

Side Tutor
├── defaultTask: side_answer
├── preferredModel: cheap
└── fallbackModel: medium
```

最终调用时：

```text
当前任务
→ Agent 自己的默认策略
→ 任务级覆盖
→ 用户手动指定
→ 全局默认模型
```

## 三、建议的优先级

推荐使用下面的模型决策顺序：

```text
用户或会话显式指定
        ↓
任务级路由配置
        ↓
Agent 级默认配置
        ↓
全局默认模型
        ↓
Provider 默认模型
```

例如：

```text
当前 Agent：Side Tutor
当前任务：side_answer
用户没有指定模型
任务路由：DeepSeek Chat
最终使用：deepseek-chat
```

如果用户在某个会话中手动指定强模型：

```text
当前会话模型覆盖：DeepSeek Reasoner
最终使用：deepseek-reasoner
```

这样既能节省成本，也保留用户控制权。

## 四、模型能力不应该只由模型名称判断

不要在代码里写死：

```python
if model == "deepseek-reasoner":
    use_for_course()
```

应该维护模型能力描述：

```json
{
  "provider": "deepseek",
  "model": "deepseek-reasoner",
  "capabilities": {
    "reasoning": "high",
    "structuredOutput": "high",
    "contextWindow": 128000,
    "speed": "medium",
    "costTier": "high"
  }
}
```

模型路由根据任务需求匹配：

```text
课程生成：
reasoning >= high
structuredOutput >= high

旁支回答：
speed >= high
reasoning >= medium

诊断：
structuredOutput >= high
costTier <= medium
```

这样以后增加：

- OpenRouter
- OpenCode
- Qwen
- GLM
- Claude
- Gemini
- 本地模型

不需要重写 Agent 逻辑。

## 五、StudyCenter 推荐的初始路由

第一版可以先使用简单配置：

```text
Main Agent / knowledge_card
→ 强模型

Teacher Agent / teacher_guidance
→ 中强模型

Side Tutor / side_answer
→ 中等模型

Diagnosis Agent / diagnosis
→ 便宜模型

Recommendation Agent / recommendation
→ 便宜模型

Bridge Agent / bridge_note
→ 便宜模型

Assessment Agent / assessment
→ 中强模型
```

更具体一点：

```json
{
  "main_agent": "strong",
  "teacher": "balanced",
  "side_tutor": "fast",
  "diagnostician": "fast",
  "recommendation": "fast",
  "bridge": "fast",
  "assessment": "balanced"
}
```

这里的 `strong / balanced / fast` 是逻辑模型档位，不直接绑定某一个 Provider。

## 六、和当前系统的关系

当前系统是：

```text
一个全局 gateway
    ↓
一个当前 provider
    ↓
一个当前 model
```

这会导致所有 Agent 使用同一个模型。

下一步应该改为：

```text
ModelRouter
    ↓
根据 task 和 agent 选择模型
    ↓
创建对应 Provider 实例
    ↓
执行调用
```

推荐接口：

```python
provider = model_router.resolve(
    task="side_answer",
    agent_id="side_tutor",
    conversation_id=conversation_id,
)
```

然后：

```python
await provider.stream_text(...)
```

结构上：

```text
AIGateway
└── ModelRouter
    ├── ProviderFactory
    ├── ModelCatalog
    ├── RoutingPolicy
    └── FallbackPolicy
```

## 七、需要考虑的几个问题

### 1. 同一个会话中是否允许切换模型

建议允许，但默认不暴露复杂配置：

- 用户可以在设置中配置模型
- 可以设置全局默认模型
- 高级设置中再设置各任务模型
- 当前会话显示实际使用的模型

### 2. 课程生成和旁支回答是否共享上下文

共享学习上下文，但不共享模型实例：

```text
课程模型负责生成知识卡
旁支模型读取知识卡和章节内容
```

### 3. 失败时怎么降级

例如：

```text
强模型不可用
→ 平衡模型
→ 快速模型
→ Mock / 明确错误
```

每次调用记录：

```text
task
agentId
provider
model
latency
token usage
cost
fallback reason
```

后面才能知道便宜模型是否真的影响学习效果。

### 4. 是否使用同一个模型处理流式和结构化任务

不一定。

例如：

```text
side_answer → 流式模型
diagnosis → 结构化模型
```

即便它们来自同一个 Provider，也可以使用不同模型。

## 八、最终建议

是的，下一步应该增加模型路由层，但建议采用：

```text
任务路由优先
Agent 默认策略辅助
用户和会话可覆盖
Provider 只负责执行
```

而不是：

```text
Teacher 永远绑定 GPT
Side Tutor 永远绑定 DeepSeek
```

推荐最终关系：

```text
Agent
  ↓
Task
  ↓
Model Routing Policy
  ↓
Provider + Model + Protocol
```

这样未来可以做到：

```text
课程生成用 Claude
老师引导用 Gemini
旁支问答用 DeepSeek
诊断用 Qwen
复杂推理用 OpenRouter 上的强模型
```

但 Agent 本身不需要知道这些 Provider 细节。

我建议下一阶段就实施：

1. 增加 `ModelRouter`
2. 增加逻辑模型档位：`strong / balanced / fast`
3. 为每个任务配置默认档位
4. 支持任务级 Provider/Model 覆盖
5. 保留当前全局默认模型作为兜底
6. 记录每次 Agent 调用的实际模型和耗时

这会是当前多 Agent 基础架构之后最重要的一层。
