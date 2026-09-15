我看过 `docs/product.md` 了。技术上建议围绕一个原则设计：

> 知识卡是核心内容对象，Agent、会话、模型和展示方式都围绕知识卡展开。

第一版可以只实现文本模型和 Markdown，但从第一天就建立统一的多模态 Provider 框架。

## 一、推荐技术栈

### 后端

- Python 3.11+
- FastAPI
- Pydantic v2
- SQLAlchemy 2
- Alembic
- SQLite 作为本地开发数据库
- PostgreSQL 作为生产数据库
- SSE 负责 AI 流式输出
- `httpx` 负责 Provider HTTP 请求
- `structlog` 或标准 logging 负责日志

不建议第一版继续使用纯内存状态。会话、知识卡和笔记都应该从一开始持久化，否则后续增加用户体系、历史记录和模型调用记录时需要重构。

### 前端

- Vue 3
- Vite
- Pinia
- Vue Router
- Axios 或原生 fetch
- Markdown-it
- Shiki 代码高亮
- Tailwind CSS
- Lucide 图标

第一版中央区域先实现 Markdown 白板；第二版互动版可以继续接入同一个主面板。

---

## 二、整体系统分层

```text
前端
├── 学习空间界面
├── 知识卡白板
├── 主会话 / 旁支会话
├── 用户笔记
└── 互动展示容器

后端 API
├── 学习空间 API
├── 知识卡 API
├── 会话 API
├── 笔记 API
├── Agent API
└── Provider 管理 API

应用层
├── 主 Agent
├── 旁支 Agent
├── 知识卡生成器
├── 断层诊断器
├── 桥接内容生成器
└── 笔记整理器

基础设施
├── Provider 抽象层
├── 模型路由
├── Prompt 管理
├── 结构化输出校验
├── 调用记录
├── 数据库
└── 文件 / 媒体资产存储
```

---

## 三、AI Provider 框架

### 1. Provider 不直接暴露给业务代码

业务层不应该直接写：

```python
openai.chat.completions.create(...)
```

而应该统一调用：

```python
result = await ai_gateway.generate(
    task="generate_knowledge_card",
    messages=messages,
    response_schema=KnowledgeCardDraft
)
```

这样主 Agent 不需要知道底层使用的是：

- OpenAI；
- Anthropic；
- Gemini；
- DeepSeek；
- 通义千问；
- 智谱；
- Ollama；
- 其他 OpenAI Compatible API。

---

### 2. Provider 能力分类

一开始就定义四类能力：

```text
TextModel
├── chat
├── streaming_chat
├── structured_output
└── tool_call

ImageModel
├── generate
└── edit

AudioModel
├── speech_to_text
└── text_to_speech

VideoModel
└── generate
```

第一版实际启用：

```text
TextModel
├── 普通问答
├── 知识卡生成
├── 断层诊断
├── 知识卡桥接
└── 用户笔记整理
```

其他能力先有接口和配置，但不接入实际业务流程。

---

### 3. 统一模型描述

每个模型都应该有统一的元数据：

```json
{
  "id": "openai:gpt-5",
  "provider": "openai",
  "model": "gpt-5",
  "capabilities": [
    "text",
    "streaming",
    "structured_output"
  ],
  "context_window": 200000,
  "enabled": true
}
```

未来可以配置：

```json
{
  "id": "google:gemini",
  "capabilities": ["text", "image_input", "structured_output"]
}
```

模型能力应该由配置描述，而不是散落在业务代码的 `if/else` 中。

---

### 4. Provider Adapter

建议设计成下面的结构：

```text
backend/
└── ai/
    ├── base.py
    ├── gateway.py
    ├── registry.py
    ├── routing.py
    ├── schemas.py
    └── providers/
        ├── openai.py
        ├── anthropic.py
        ├── google.py
        ├── openai_compatible.py
        └── mock.py
```

其中：

- `base.py`：定义统一接口；
- `registry.py`：注册和发现模型；
- `routing.py`：根据任务选择模型；
- `gateway.py`：业务层统一入口；
- `providers/`：各厂商适配器；
- `mock.py`：没有 API Key 时提供演示能力。

第一版可以先实现：

- OpenAI Adapter；
- OpenAI Compatible Adapter；
- Mock Adapter。

这样国内模型和本地模型通常可以通过 Compatible Adapter 接入。

---

## 四、任务路由，而不是只配置一个默认模型

系统不应该只有一个 `DEFAULT_MODEL`。

应该按照任务配置模型：

```yaml
routing:
  main_agent:
    model: openai:gpt-5
  side_agent:
    model: openai:gpt-5-mini
  knowledge_card:
    model: openai:gpt-5
  note_organizer:
    model: openai:gpt-5-mini
  image_generation:
    model: openai:gpt-image
  text_to_speech:
    model: elevenlabs:default
```

第一版可以先使用同一个文本模型，但接口上保留任务路由。

未来可以做到：

- 主 Agent 使用高质量模型；
- 旁支问答使用快速模型；
- 笔记整理使用低成本模型；
- 图片、音频和视频使用独立 Provider。

---

## 五、模型配置和密钥管理

模型配置建议支持环境变量和配置文件：

```env
OPENAI_API_KEY=
OPENAI_BASE_URL=
ANTHROPIC_API_KEY=
GOOGLE_API_KEY=
DEEPSEEK_API_KEY=
OLLAMA_BASE_URL=http://localhost:11434
```

配置文件只保存：

- Provider 名称；
- Base URL；
- 模型名称；
- 能力；
- 默认路由；
- 是否启用。

API Key 只从环境变量或安全配置读取，不进入数据库，也不发送给前端。

前端只能看到：

```text
当前可用模型：GPT / DeepSeek / Ollama
```

不能看到完整密钥。

---

## 六、知识卡的数据模型

建议先确定这些核心对象。

```text
LearningSpace
├── id
├── title
├── description
├── root_card_id
├── current_card_id
├── current_section_id
└── created_at

KnowledgeCard
├── id
├── learning_space_id
├── parent_card_id
├── source_session_id
├── title
├── summary
├── status
├── content_markdown
├── card_type
├── created_at
└── updated_at

CardSection
├── id
├── card_id
├── title
├── order_index
├── content_markdown
└── learning_status

Conversation
├── id
├── learning_space_id
├── card_id
├── section_id
├── conversation_type
├── title
├── root_question
├── status
└── created_at

Message
├── id
├── conversation_id
├── role
├── content
├── message_type
├── metadata
└── created_at

Note
├── id
├── user_id
├── card_id
├── section_id
├── conversation_id
├── content
├── source_message_id
└── created_at
```

关键关系：

```text
学习空间 1 → N 知识卡
知识卡 1 → N 章节
知识卡 1 → N 会话
会话 1 → N 消息
知识卡 1 → N 笔记
```

`parent_card_id` 用来表达知识卡挂接关系：

```text
主知识卡
└── 关联知识卡
    └── 更深层关联知识卡
```

第一版可以支持多层数据关系，但界面上先限制为一层旁支，避免交互复杂化。

---

## 七、Agent 的实现方式

Agent 不应该直接操作数据库，而应该通过应用服务完成动作。

例如主 Agent 输出：

```json
{
  "action": "UPDATE_CARD",
  "card_id": "card-001",
  "section_id": "section-002",
  "content_markdown": "...",
  "next_section": false
}
```

旁支 Agent 输出：

```json
{
  "reply": "...",
  "diagnosis": {
    "has_knowledge_gap": true,
    "missing_topics": [
      "Linux 进程",
      "PID Namespace"
    ]
  },
  "proposal": {
    "title": "Linux 进程与命名空间",
    "reason": "..."
  }
}
```

后端负责：

1. 调用模型；
2. 校验结构化输出；
3. 执行业务动作；
4. 写入数据库；
5. 通过 SSE 推送前端。

不要让模型直接决定数据库写入细节。

---

## 八、主 Agent 和旁支 Agent 的上下文边界

### 主 Agent 上下文

包含：

- 学习空间信息；
- 当前主知识卡；
- 当前章节；
- 已完成章节；
- 用户相关笔记；
- 主会话历史；
- 关联知识卡摘要。

### 旁支 Agent 上下文

包含：

- 来源知识卡；
- 来源章节；
- 当前用户问题；
- 当前旁支会话历史；
- 相关用户笔记；
- 必要的主线内容摘要。

旁支 Agent 不应该默认加载整个学习空间，否则上下文会越来越重，也容易让回答偏离当前问题。

---

## 九、流式响应和事件模型

聊天不建议只返回一次完整 JSON，而应支持流式事件。

```text
message.start
message.delta
message.complete
diagnosis.updated
proposal.created
card.created
bridge_note.created
note.saved
```

例如旁支会话中：

```text
message.delta
→ AI 正在回答

diagnosis.updated
→ 检测到可能缺少前置知识

proposal.created
→ 显示“是否生成知识卡”

card.created
→ 用户确认后生成关联知识卡
```

这样未来切换互动版时，也可以增加：

```text
display_mode.suggested
interactive_content.created
```

前端不需要重新设计通信方式。

---

## 十、互动版的技术预留

虽然互动版放到第二版，但第一版的数据结构中建议预留统一的展示内容模型：

```json
{
  "id": "content-001",
  "conversation_id": "conversation-001",
  "card_id": null,
  "display_mode": "markdown",
  "content": "...",
  "structured_data": null
}
```

未来可以支持：

```json
{
  "display_mode": "flowchart",
  "content": "Namespace 隔离流程",
  "structured_data": {
    "nodes": [],
    "edges": []
  }
}
```

展示模式可以包括：

```text
markdown
table
flowchart
timeline
mindmap
comparison
simulation
```

第一版只真正实现 `markdown`，但 API 和数据库不要把内容字段设计成只能存 Markdown。

---

## 十一、多 Agent 的技术预留

第二版旁支多 Agent 可以建立在同一个会话上：

```text
Conversation
└── AgentRun
    ├── ExplainerAgent
    ├── SocraticAgent
    ├── ExampleAgent
    └── ReviewerAgent
```

第一版可以让一个旁支 Agent 完成所有职责，但内部概念上保留：

```text
agent_role = side_tutor
```

未来扩展为：

```text
agent_role = explainer
agent_role = socratic_coach
agent_role = example_expert
agent_role = reviewer
```

这样不需要重写会话模型。

---

## 十二、第一版必须实现的基础能力

第一版虽然只做 Markdown 和文本聊天，但基础框架应包含：

- Provider 抽象层；
- OpenAI Provider；
- OpenAI Compatible Provider；
- Mock Provider；
- 模型能力声明；
- 按任务选择模型；
- 统一结构化输出；
- SSE 流式聊天；
- 学习空间持久化；
- 知识卡持久化；
- 章节持久化；
- 主会话和旁支会话；
- 用户笔记；
- Provider 调用日志；
- Prompt 版本管理；
- 统一错误处理。

暂时不实现：

- 图片生成；
- 视频生成；
- 语音合成；
- 语音识别；
- 互动版渲染；
- 多 Agent 并行协作。

但这些能力在接口、配置和数据模型上预留扩展点。

## 十三、建议的后端目录

```text
backend/
├── main.py
├── config.py
├── database.py
├── models/
│   ├── learning_space.py
│   ├── knowledge_card.py
│   ├── conversation.py
│   ├── message.py
│   └── note.py
├── schemas/
│   ├── learning_space.py
│   ├── knowledge_card.py
│   ├── conversation.py
│   └── ai.py
├── api/
│   ├── learning_spaces.py
│   ├── cards.py
│   ├── conversations.py
│   ├── notes.py
│   └── ai.py
├── services/
│   ├── learning_space_service.py
│   ├── knowledge_card_service.py
│   ├── conversation_service.py
│   ├── note_service.py
│   └── bridge_service.py
├── agents/
│   ├── main_agent.py
│   ├── side_agent.py
│   ├── prompts.py
│   └── output_parser.py
├── ai/
│   ├── base.py
│   ├── gateway.py
│   ├── registry.py
│   ├── routing.py
│   └── providers/
│       ├── openai.py
│       ├── openai_compatible.py
│       └── mock.py
└── migrations/
```

## 十四、最终架构判断

第一版不应该被实现成：

```text
一个聊天框 + 一个大模型
```

而应该是：

```text
学习空间
├── 主知识卡
├── 关联知识卡
├── 主会话
├── 旁支会话
├── 用户笔记
├── Agent 层
└── 可扩展 AI Provider 层
```

其中 Provider 层负责“模型能力”，Agent 层负责“教学行为”，知识卡负责“内容沉淀”，会话负责“交互过程”。

这四层分开后，后续加入图片、视频、音频、互动白板和多 Agent，都不会破坏第一版的数据模型。

---

## 十五、接口契约规范

前后端采用 Contract-first 方式协作。`contracts/openapi.yaml` 是 HTTP 接口的唯一权威定义，前端 TypeScript 类型和 API Client 从该文件生成，后端使用 FastAPI 实现并通过契约测试保持一致。

### 15.1 基本约定

- 所有接口使用 `/api/v1` 前缀。
- 请求和响应使用 JSON，字段使用 `camelCase`。
- ID 使用字符串，具体格式由后端生成，前端不依赖其内部结构。
- 时间统一使用 ISO 8601 UTC 字符串。
- 分页接口统一使用 `items`、`nextCursor`。
- 生成代码目录禁止手动修改。
- 破坏性变更通过新的 API 版本处理。

### 15.2 核心资源

```text
LearningSpace
├── KnowledgeCard
│   └── CardSection
├── Conversation
│   └── Message
└── Note
```

知识卡通过 `parentCardId` 建立挂接关系；旁支会话通过 `cardId` 和 `sectionId` 记录其来源位置；知识卡是沉淀内容，会话是交互过程。

### 15.3 主要 HTTP 接口

```text
POST   /api/v1/learning-spaces
GET    /api/v1/learning-spaces/{spaceId}

GET    /api/v1/learning-spaces/{spaceId}/cards
GET    /api/v1/cards/{cardId}
POST   /api/v1/cards/{cardId}/related
POST   /api/v1/cards/{cardId}/complete

GET    /api/v1/cards/{cardId}/conversations
POST   /api/v1/cards/{cardId}/conversations
GET    /api/v1/conversations/{conversationId}
POST   /api/v1/conversations/{conversationId}/messages/stream

POST   /api/v1/proposals/{proposalId}/accept
POST   /api/v1/proposals/{proposalId}/reject

GET    /api/v1/cards/{cardId}/notes
POST   /api/v1/cards/{cardId}/notes
PATCH  /api/v1/notes/{noteId}
DELETE /api/v1/notes/{noteId}
```

### 15.4 SSE 事件

流式消息使用 `text/event-stream`，事件名称和数据结构也属于接口契约：

```text
message.started
message.delta
message.completed
diagnosis.updated
related_card.proposed
related_card.created
bridge_note.created
run.failed
```

用户确认和 AI 提议必须是两个动作。AI 只能生成 `related_card.proposed`，用户确认后后端才创建关联知识卡。

### 15.5 统一错误

```json
{
  "error": {
    "code": "AI_OUTPUT_INVALID",
    "message": "AI 返回内容无法通过结构校验",
    "details": {},
    "requestId": "req_123"
  }
}
```

### 15.6 契约生成和检查

建议使用 `openapi-typescript` 生成前端类型，使用 `openapi-fetch` 调用接口。生成命令完成后，CI 执行生成并检查工作区是否产生差异；如果契约变了但生成代码未更新，则构建失败。

Agent 的结构化输出另行使用 Pydantic 和 JSON Schema 定义，不与 HTTP DTO 混为一体。

---

## 十六、实施 Todo

### Phase 0：工程和契约基础

- [x] 确认前后端目录和本地启动方式
- [x] 建立 `contracts/openapi.yaml`
- [x] 定义公共错误、分页、SSE 事件 Schema
- [x] 定义学习空间、知识卡、章节、会话、消息、笔记 DTO
- [x] 配置前端 TypeScript Client 生成
- [x] 配置契约校验和生成代码检查

### Phase 1：后端基础

- [x] FastAPI 应用和 `/api/v1` 路由
- [x] SQLAlchemy 数据库连接
- [x] SQLite 本地配置和 Alembic 初始化
- [x] 核心数据表和基础 CRUD
- [x] 统一错误处理和 requestId
- [x] 学习空间、知识卡、会话、笔记接口

Phase 1 当前使用 `uv` 管理 Python 工程：

```bash
cd backend
uv run alembic upgrade head
cd ..
uv --project backend run uvicorn backend.main:app --reload
```

消息发送会先持久化用户消息，AI 流式完成后再持久化 assistant 消息；知识卡通过 `parentCardId` 保留主线与关联卡的挂接关系。

### Phase 2：AI 基础

- [x] Provider 抽象接口
- [x] OpenAI Provider
- [x] OpenAI Compatible Provider
- [x] Mock Provider
- [x] Provider Registry 和任务路由
- [x] 结构化 Agent 输出校验
- [x] 主 Agent 生成主知识卡
- [x] 旁支 Agent 普通问答和断层诊断
- [x] SSE 流式消息

### Phase 3：第一版核心交互

- [ ] 创建学习空间并生成主知识卡
- [ ] 主知识卡章节切换
- [ ] 从具体章节创建旁支会话
- [ ] 用户确认生成关联知识卡
- [ ] 关联知识卡挂接和返回主线
- [ ] 生成桥接提示
- [ ] 用户手动创建和保存笔记
- [ ] 保存 AI 回复为笔记

### Phase 4：第二版扩展

- [ ] 互动展示协议和渲染容器
- [ ] 流程图、表格、关系图等展示类型
- [ ] 多 Agent 旁支会话
- [ ] 图片、音频、视频 Provider
- [ ] 多模态资产存储
- [ ] 知识卡关联图

当前实施优先级是 Phase 0 → Phase 1 → Phase 2，先建立可以稳定迭代的契约和运行骨架，再实现完整学习闭环。

Phase 2 当前已实现 Provider、主 Agent、旁支诊断、SSE 和关联知识卡提议闭环；真实多模态 Provider、互动展示和多 Agent 角色聊天仍按第二版范围保留。
