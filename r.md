这份文档是专为 **FastAPI（后端）+ Vue 3（前端）** 架构定制的产品需求与技术设计文档。你可以直接将本文档作为 Prompt 发送给 Codex、Claude Code 或 Cursor，让其生成前后端完整工程。

---

# 📚 全栈项目工程规格书：DualTrack-Learn (FastAPI + Vue 3)

## 1. 系统架构与工程目录

采用前后端分离架构，最小化外部依赖，确保开箱即用：

```text
dualtrack-learn/
├── backend/                   # FastAPI 后端工程
│   ├── main.py                # 路由入口与 CORS 配置
│   ├── schemas.py             # Pydantic 数据模型定义
│   ├── state_manager.py       # 会话内存状态机 (In-Memory Session Store)
│   ├── agents.py              # LLM 调用与 Prompt 逻辑 (含 Mock 降级)
│   └── requirements.txt       # fastapi, uvicorn, pydantic, openai, python-dotenv
│
└── frontend/                  # Vue 3 前端工程
    ├── src/
    │   ├── App.vue            # 主页面布局 (左右分栏 + 顶部面包屑)
    │   ├── stores/
    │   │   └── learning.js    # Pinia 状态管理
    │   ├── components/
    │   │   ├── Breadcrumb.vue # 顶部调用栈面包屑
    │   │   ├── Blackboard.vue # 左侧黑板 (Markdown 渲染 + 桥接便签)
    │   │   ├── ChatDrawer.vue # 右侧抽屉答疑区
    │   │   └── ActionCard.vue # 副本提议确认卡片
    │   └── main.js
    ├── package.json           # vue, pinia, axios, markdown-it, lucide-vue-next, tailwindcss
    └── vite.config.js
```

---

## 2. 后端数据协议与 API 契约（Backend Spec）

### 2.1 Pydantic 核心数据模型 (`backend/schemas.py`)

```python
from pydantic import BaseModel, Field
from typing import List, Optional

class Chapter(BaseModel):
    id: int
    title: str
    board_markdown: str

class CourseState(BaseModel):
    course_id: str
    title: str
    chapters: List[Chapter]
    current_chapter_index: int = 0
    bridge_note: Optional[str] = None  # 弹栈返回时注入的高亮便签

class StackFrame(BaseModel):
    paused_course: CourseState
    reason: str
    chat_history_snapshot: List[dict]

class SubQuestProposal(BaseModel):
    title: str
    reason: str

class ChatMessage(BaseModel):
    role: str   # "user" | "assistant" | "system"
    content: str
    type: str = "text"  # "text" | "subquest_proposal"
    proposal_data: Optional[SubQuestProposal] = None

class SessionState(BaseModel):
    session_id: str
    active_course: CourseState
    course_stack: List[StackFrame] = Field(default_factory=list)
    chat_history: List[ChatMessage] = Field(default_factory=list)

# API 请求/响应对象
class UserMessageRequest(BaseModel):
    session_id: str
    message: str

class EnterSubQuestRequest(BaseModel):
    session_id: str
    subquest_title: str
```

### 2.2 API 端点设计 (`backend/main.py`)

* `GET /api/session/{session_id}`: 获取当前会话的完整状态（黑板、栈深度、消息历史）。
* `POST /api/chat`: 发送用户提问，触发 Diagnostic TA Agent：
  * 若为普通答疑，直接向 `chat_history` 追加回复。
  * 若诊断出知识卡点，追加一条 `type: "subquest_proposal"` 的消息。
  * 若表达进入下一节，自动递增 `current_chapter_index` 并刷新黑板。
* `POST /api/subquest/enter`: 用户点击确认进入副本：
  * **压栈**：将当前 `active_course` 与聊天切片压入 `course_stack`。
  * 生成并激活微课大纲，黑板切至微课第 1 节。
* `POST /api/subquest/finish`: 用户学完微课点击返回：
  * **弹栈**：取出父级课程，恢复原黑板。
  * 生成并在黑板顶部挂载 `bridge_note`（知识衔接便签）。

---

## 3. Agent 核心 Prompt 与输出结构 (`backend/agents.py`)

大模型调用需强制指定为 **JSON Mode**。同时提供预置的 **Mock Fallback**，以便在没有 API Key 时也能完整演示“K8s 容器 $\rightarrow$ Linux 进程内核”的经典跳转。

### 3.1 诊断助教 Agent Prompt (Diagnostic Agent)
```text
System:
你是一名资深架构师教学助教。请诊断学生的最新输入，结合当前黑板内容判断认知状态。

【当前黑板内容】
{board_markdown}

【当前学习主题】
{course_title}

【决策规则】
1. NORMAL_ANSWER: 属于当前主题理解范围内的正常发问，给予简短启发式解答。
2. PROPOSE_SUB_QUEST: 用户表现出明显缺失更底层的前置依赖（如：学容器隔离却完全不懂 Linux 进程与系统调用）。
3. PROCEED_NEXT: 用户表达已理解、准备进入下一节。

【必须严格返回如下 JSON】
{
  "action": "NORMAL_ANSWER" | "PROPOSE_SUB_QUEST" | "PROCEED_NEXT",
  "reply": "给用户的回复文本",
  "subquest": {
    "title": "建议的前置微课标题（如：Linux 进程与内核隔离本质）",
    "reason": "为什么需要先补这个课的比喻与说明"
  } // action 为 PROPOSE_SUB_QUEST 时必填，否则为 null
}
```

### 3.2 知识桥接 Agent Prompt (Bridge Agent)
```text
System:
学生刚学完前置微课《{subquest_title}》，现返回主线章节《{resumed_chapter}》。
请生成一句 30 字以内的穿透性金句便签，解释刚才学到的前置概念如何直接解密当前主线内容。
格式要求：纯文本，以 "📌 认知打通：" 开头。
```

---

## 4. 前端状态与组件规格（Frontend Spec - Vue 3）

### 4.1 Pinia 状态树 (`frontend/src/stores/learning.js`)

```javascript
import { defineStore } from 'pinia';
import axios from 'axios';

export const useLearningStore = defineStore('learning', {
  state: () => ({
    sessionId: 'demo-session-001',
    activeCourse: {
      title: '',
      current_chapter_index: 0,
      chapters: [],
      bridge_note: null
    },
    courseStack: [],       // 存放被挂起的课程快照
    chatHistory: [],       // 消息流
    isLoading: false
  }),
  getters: {
    currentChapter: (state) => state.activeCourse.chapters[state.activeCourse.current_chapter_index] || {},
    isInSubQuest: (state) => state.courseStack.length > 0
  },
  actions: {
    async fetchState() { /* GET /api/session/{id} */ },
    async sendMessage(text) { /* POST /api/chat */ },
    async enterSubQuest(title) { /* POST /api/subquest/enter */ },
    async finishSubQuest() { /* POST /api/subquest/finish */ }
  }
});
```

### 4.2 核心界面组件设计

#### 1. 顶部面包屑 (`Breadcrumb.vue`)
* 动态响应 `courseStack`：
  * 当 `courseStack` 为空：显示 `[主线课程: K8s 进阶]`。
  * 当有压栈时：显示 `[主线: K8s 进阶] ──(⏸️ 已挂起)──> ⚡ [当前微课: Linux 进程与隔离本质]`。

#### 2. 左侧黑板区 (`Blackboard.vue`)
* 宽度占比：60%（桌面端）。
* **顶部 Bridge 提示条**：若 `activeCourse.bridge_note` 存在，渲染一个淡黄色高亮通知栏，带关闭按钮。
* **主体区域**：使用 `markdown-it` 渲染 `currentChapter.board_markdown`。
* **底部控制条**：
  * 若处于普通章节：显示 `[掌握了，进入下一节]`。
  * 若处于微副本模式（`isInSubQuest == true`）：显示醒目的绿色按钮 **`[ ✅ 已掌握核心，完成微课并返回主线 ]`**。

#### 3. 右侧交互抽屉 (`ChatDrawer.vue`)
* 宽度占比：40%，右侧独立滚动。
* 普通消息以气泡展示。
* 当收到 `type: "subquest_proposal"` 时，渲染 **`ActionCard.vue`**：
  * 显示助教建议：“检测到您可能需要先了解 Linux 进程机制……”
  * 提供按钮：`[ 🚀 切入 10 分钟前置微课 ]`，点击直接调用 `enterSubQuest`。

---

## 5. 初始体验演示数据（Mock Data Setup）

为了让 Codex 生成完代码后能**即刻开箱测试**，在 `backend/state_manager.py` 中预置初始课程：

* **主线课程**：《Kubernetes 容器深入解析》
  * 第 1 节：容器镜像的只读层与读写层
  * 第 2 节：容器运行时与资源隔离机制（**默认停留在本节**）
    * 初始板书内容：包含 Namespaces 隔离概念及一段带 cgroups 配置的 yaml 示例。
* **Mock 问答预设**：
  * 当用户在输入框发送任何包含 `进程`、`内核`、`共用`、`怎么隔离` 的文本时：
    Mock 模式自动返回 `action: "PROPOSE_SUB_QUEST"`，推荐微课《Linux 进程与内核隔离本质》。

---

## 6. 给 Codex 的代码生成执行指令（Prompt to Codex）

你可将以下整段 Prompt 直接粘给 AI 编程助手：

> **指令：**
> “请按照上述产品与技术设计规范，完整生成 `dualtrack-learn` 项目的前后端代码。
> 
> **实现要求：**
> 1. **后端（FastAPI）**：
>    - 包含完整的 CORS 中间件（允许来自前端 Vite 端口的访问）。
>    - 实现 `StateManager` 内存字典，并预置好初始的 K8s 课程数据与 Mock 逻辑。
>    - 使用标准的 `AsyncOpenAI` 客户端，若环境变量中无 `OPENAI_API_KEY`，则自动平滑降级到 Mock 数据，保证无需配置 API 也能体验全流程。
> 2. **前端（Vue 3 + Vite）**：
>    - 使用 Tailwind CSS 实现现代极简的 UI 风格。
>    - 严格实现左侧 Markdown 黑板（含便签高亮）、右侧抽屉式聊天、顶部调用栈面包屑。
>    - 当用户点击‘切入微课’与‘返回主线’时，界面黑板与面包屑必须平滑更新。
> 3. 提供完整的 `requirements.txt` 与 `package.json`，并在根目录提供一份简洁的 `README.md`，说明两端各自的启动命令。”
