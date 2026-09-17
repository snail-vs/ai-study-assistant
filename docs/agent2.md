我调研了 OpenMAIC。核心结论是：

> OpenMAIC 主要不是“每个 Agent 一个模型”，而是“每类任务/阶段一个模型路由”。
> Agent 负责角色、提示词、权限和行为，模型由当前任务阶段决定。

## 1. OpenMAIC 的模型路由方式

OpenMAIC 使用 `MODEL_ROUTES` 按任务阶段配置模型，例如：

```env
MODEL_ROUTES='{
  "scene-outlines-stream": {
    "model": "openai:gpt-5.5",
    "api": "openai-completions"
  },
  "scene-content": {
    "model": "anthropic:claude-sonnet",
    "api": "anthropic-messages"
  },
  "pbl-chat": {
    "model": "deepseek:deepseek-chat"
  }
}'
```

它的路由 key 不是 Agent 名称，而是功能阶段，例如：

- `scene-outlines-stream`：生成课程大纲
- `scene-content`：生成白板内容
- `scene-actions`：生成互动动作
- `agent-profiles`：生成 Agent 角色
- `pbl-chat`：问题驱动学习聊天
- `chat-adapter`：聊天适配
- `conversation-title`：生成会话标题
- `maic-agent-driver`：多 Agent 运行时的调度模型

相关设计可以参考 OpenMAIC 的[模型路由 RFC](https://github.com/THU-MAIC/OpenMAIC/issues/745)和[环境变量示例](https://github.com/THU-MAIC/OpenMAIC/blob/main/.env.example)。

OpenMAIC 当前的解析顺序大致是：

```text
任务阶段路由
  ↓
请求级模型覆盖
  ↓
全局默认模型
```

并且明确不做自动学习路由，也不让普通用户在每个阶段单独选择模型。

## 2. OpenMAIC 中 Agent 和模型的关系

OpenMAIC 的 Agent 主要由这些属性组成：

```text
id
name
role
persona
avatar
color
priority
allowedActions
```

例如：

- AI Teacher：负责讲解和推进教学
- Teaching Assistant：补充知识、解释难点
- Curious Student：代表学生提出问题
- Challenger：质疑和反例
- Note Taker：总结要点
- Thinker：进行更深层次思考

这些角色主要影响：

- System Prompt
- 发言风格
- 可以执行的动作
- 在课堂中的职责
- 是否可以操作白板

参考 OpenMAIC 的[Agent 类型定义](https://raw.githubusercontent.com/THU-MAIC/OpenMAIC/refs/heads/main/lib/orchestration/registry/types.ts)。

但是，Agent 本身通常不绑定一个模型。比如：

```text
Teacher + 当前任务是生成白板
    → 使用课程内容生成模型

Teacher + 当前任务是回答问题
    → 使用问答模型

Teacher + 当前任务是多 Agent 调度
    → 使用 Director 模型
```

也就是说：

```text
Agent = 谁在说、怎么说、能做什么

Task / Stage = 当前要完成什么工作

Model Route = 这个工作使用哪个模型
```

## 3. OpenMAIC 的多 Agent 协作方式

OpenMAIC 使用 Director Graph 负责多 Agent 协作。

流程类似：

```text
用户发言
   ↓
Director 判断下一步
   ↓
选择 Agent
   ↓
Agent 生成回复或动作
   ↓
返回前端事件
```

Director 可以决定：

- 让哪个 Agent 回答
- 是否继续讨论
- 是否让用户接管
- 是否结束当前轮次
- 是否切换到另一个 Agent

相关实现见 OpenMAIC 的[Director Graph](https://raw.githubusercontent.com/THU-MAIC/OpenMAIC/refs/heads/main/lib/orchestration/director-graph.ts)。

它的状态中包含：

```text
messages
availableAgentIds
currentAgentId
triggerAgentId
turnCount
agentResponses
discussionContext
whiteboardLedger
userProfile
agentConfigOverrides
```

不过需要特别注意：

> OpenMAIC 的 Director 目前更像“调度器”，而不是每个 Agent 都独立运行一个完全不同的模型。

多 Agent 的主要差异来自：

- Agent 角色
- Agent Persona
- Agent Prompt
- 可用 Action
- 发言长度
- 当前教学上下文

而不是简单地给每个角色绑定不同模型。

## 4. OpenMAIC 的 Agent Prompt 设计

OpenMAIC 会为每个 Agent 生成独立的系统提示词，里面包含：

```text
角色定义
Persona
当前课堂状态
已有对话
其他 Agent 的发言
白板状态
当前讨论上下文
可用动作
发言长度限制
```

例如：

```text
Teacher：
负责推进教学，提出问题，引导学生理解，不要一次讲完所有内容。

Assistant：
负责补充关键知识点，避免重复教师已经讲过的内容。

Student：
只表达简短反应、疑问或误解，不进行长篇教学。
```

OpenMAIC 还对不同角色设置了不同的回答长度，教师通常比学生更长，学生只进行短回应。

参考其[Prompt Builder](https://raw.githubusercontent.com/THU-MAIC/OpenMAIC/refs/heads/main/lib/orchestration/prompt-builder.ts)。

这里有一个值得注意的实现细节：Agent 的历史消息有时会被重新编码成：

```text
[Teacher]: ...
[Assistant]: ...
[Student]: ...
```

然后以 `user` 消息形式传给模型。这种做法简单，但需要非常清晰的 Prompt，否则模型可能混淆“用户发言”和“其他 Agent 发言”。

## 5. OpenMAIC 的教学阶段结构

OpenMAIC 的课程生成大致分成：

```text
课程大纲
   ↓
场景内容
   ↓
白板页面
   ↓
互动动作
   ↓
课堂 Agent 运行
```

它的 DSL 中已经把 Agent 和 Stage 联系起来，但依然不是直接把模型绑定到 Agent：

```text
Stage
 ├── agentIds
 ├── generatedAgentConfigs
 └── multiAgent
      ├── enabled
      ├── agentIds
      └── directorPrompt
```

参考 OpenMAIC 的[Stage DSL 定义](https://github.com/THU-MAIC/OpenMAIC/blob/main/packages/@openmaic/dsl/src/stage.ts)。

这说明它的关系是：

```text
一个教学阶段
  → 使用哪些 Agent

一个任务阶段
  → 使用哪个模型
```

两个维度是分开的。

## 6. 对 StudyCenter 的启发

我们现在的设计可以沿用这个方向，但要适配我们的产品结构。

建议采用：

```text
Agent 角色层
任务路由层
Provider / Model 层
```

### Agent 角色层

负责：

- 主 Agent：生成课程、讲解、推进教学
- 教师 Agent：当前章节的引导和诊断
- 旁支 Tutor：回答用户问题
- Gap Diagnostician：识别知识断层
- Recommendation Agent：生成推荐知识卡
- Note Assistant：帮助整理用户笔记
- Director：未来负责旁支群聊调度

### 任务路由层

负责描述当前到底在做什么：

```text
card_outline
card_section_content
teacher_guidance
side_answer
gap_diagnosis
knowledge_recommendation
knowledge_card_generation
conversation_title
note_assist
group_director
```

### Provider / Model 层

负责：

```text
provider
model
api protocol
thinking
token limit
timeout
fallback
```

例如：

```text
deepseek:deepseek-chat
openrouter:anthropic/claude-sonnet
opencode:gpt-6-astra
```

Provider 决定 API 协议，模型不直接决定协议。这和我们前面确定的设计是一致的。

## 7. StudyCenter 推荐的模型路由

建议第一版定义成下面这样：

```yaml
model_routes:
  card_outline:
    model: deepseek:deepseek-reasoner
    thinking: true

  card_section_content:
    model: deepseek:deepseek-reasoner
    thinking: true

  teacher_guidance:
    model: deepseek:deepseek-chat
    thinking: false

  side_answer:
    model: deepseek:deepseek-chat
    thinking: false

  gap_diagnosis:
    model: deepseek:deepseek-chat
    thinking: false

  knowledge_recommendation:
    model: deepseek:deepseek-chat
    thinking: false

  note_assist:
    model: deepseek:deepseek-chat
    thinking: false

  group_director:
    model: deepseek:deepseek-reasoner
    thinking: true
```

大致策略是：

| 任务 | 模型策略 |
|---|---|
| 课程大纲 | 强模型 |
| 白板内容生成 | 强模型 |
| 教师引导 | 中等模型 |
| 旁支问答 | 便宜、快速模型 |
| 知识断层识别 | 中等模型 |
| 推荐知识卡 | 中等模型 |
| 笔记辅助 | 快速模型 |
| 多 Agent Director | 中等或强模型 |

## 8. 是否需要“每个 Agent 一个模型”？

我的建议是：

> 第一阶段不要直接做 Agent → Model 的绑定，而是使用 Task → Model 路由。

原因有三个：

1. 同一个 Agent 在不同任务中需要不同能力。

```text
Teacher 生成课程
Teacher 讲解章节
Teacher 诊断问题
Teacher 参与群聊
```

这些任务的模型要求不同。

2. 任务路由更容易观测和优化。

我们可以直接知道：

```text
card_section_content 使用了什么模型
side_answer 是否需要更强模型
gap_diagnosis 的准确率如何
```

3. 未来切换 Provider 更简单。

比如：

```text
side_answer:
  从 DeepSeek 切换到 OpenRouter

card_section_content:
  从 DeepSeek 切换到 Claude
```

不需要修改 Agent 定义。

## 9. 最终建议的架构

```text
用户请求
   ↓
确定 conversation
   ↓
确定当前 Agent
   ↓
确定 task
   ↓
Model Router 根据 task 选择模型
   ↓
Provider Gateway
   ↓
对应协议 Adapter
   ↓
返回文本 / 结构化内容 / SSE 事件
```

代码层面可以是：

```python
route = model_router.resolve(
    task="side_answer",
    conversation=conversation,
    agent_id="side_tutor",
)

response = gateway.stream(
    model=route.model,
    protocol=route.protocol,
    messages=messages,
)
```

同时建议所有请求记录：

```text
task
agent_id
provider
model
protocol
latency
input_tokens
output_tokens
fallback_used
error
```

这样后续才能评估“贵模型是否真的提升了教学效果”。

## 结论

OpenMAIC 给我们的最重要参考不是“多 Agent 使用多个模型”，而是：

> Agent 的角色和模型路由解耦；模型按照教学阶段和任务类型配置。

所以 StudyCenter 最合理的方向是：

```text
Agent 决定角色和行为
Task 决定工作类型
Model Router 决定模型
Provider Adapter 决定调用协议
```

后续如果要支持多角色群聊，只需要增加：

```text
group_director
agent_turn_selection
agent_response
```

这些任务路由，不需要重构现有 Agent 体系。
