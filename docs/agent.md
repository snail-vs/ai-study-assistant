下面按“创建知识卡 → 学习章节 → 旁支提问 → 知识断层 → 关联学习”的完整链路梳理。

## 一、整体教学流程

```text
用户输入学习目标
        ↓
主 Agent 生成课程知识卡
        ↓
用户进入某个章节
        ↓
老师 Agent 进行章节导入
        ↓
用户阅读白板内容
        ↓
用户在旁支会话提问
        ↓
旁支 Agent 回答问题
        ↓
诊断 Agent 判断理解情况
        ↓
老师 Agent 总结并重新连接主线
        ↓
发现知识断层
        ↓
推荐知识卡
        ↓
用户继续讨论 / 创建 / 暂不处理
        ↓
关联知识卡生成
        ↓
Bridge Agent 解释新旧知识关系
```

目前系统已经有这些 Agent：

- Main Agent：生成知识卡
- Side Agent：回答旁支问题并诊断知识断层
- Teacher Agent：章节导入和问题后的老师引导
- Bridge Agent：生成主卡和关联卡之间的知识桥接说明

但目前这些 Agent 主要由 API 层串联，还没有真正的“教学编排 Agent”。后续建议增加一个 Orchestrator 作为统一调度层。

---

## 二、每个 Agent 的职责

### 1. Learning Orchestrator：教学编排层

这是建议新增的核心调度层，不直接负责大量内容生成，而是决定：

- 当前用户处于哪个知识卡、哪个章节
- 当前该调用哪个 Agent
- 是否需要调用诊断
- 是否需要生成老师引导
- 是否创建推荐知识卡
- 是否更新学习状态
- 是否触发测验或复习

例如：

```text
进入章节
→ 获取章节内容
→ 获取历史老师引导
→ 没有引导则调用 Teacher Agent

旁支问题
→ 构建当前学习上下文
→ 调用 Side Tutor
→ 调用 Diagnosis
→ 必要时调用 Teacher Agent
→ 必要时创建 Recommendation
```

这样可以避免业务逻辑全部堆在 `api.py` 中，也方便以后增加测验、复习、评分等能力。

---

### 2. Main Agent：课程与知识卡生成

当前职责：

```text
学习目标 → 知识卡 → 多个章节 → Markdown 白板内容
```

现在主要生成：

- 知识卡标题
- 章节标题
- 章节 Markdown 内容
- 解释、示例、小结

建议进一步要求它输出教学结构，而不仅是 Markdown：

```json
{
  "title": "Linux 进程的本质",
  "summary": "...",
  "prerequisites": ["操作系统基础"],
  "sections": [
    {
      "title": "进程是什么",
      "objective": "理解进程是资源和执行状态的组合",
      "contentMarkdown": "...",
      "keyPoints": ["...", "..."],
      "commonMisconceptions": ["..."],
      "checkQuestions": ["..."]
    }
  ]
}
```

这样后续 Agent 才能知道：

- 这一节希望学生学会什么
- 哪些内容最重要
- 学生可能在哪里误解
- 旁支问题是否偏离本节目标
- 什么时候可以进入下一节

白板仍然只展示 `contentMarkdown`，其他字段作为教学元数据使用。

---

### 3. Teacher Agent：老师引导学习

Teacher Agent 不负责重复白板内容，也不负责回答所有问题。

它主要有两个触发点。

#### 进入章节

生成简短导入：

```text
这一节我们重点理解进程为什么不仅是一个程序，
还包含资源、状态和内核管理信息。
阅读时可以特别关注进程和 namespace 的关系。
```

它应该完成三个动作：

1. 告诉学生这节课要学什么
2. 提醒学生应该关注什么
3. 把本节和前后章节连接起来

#### 旁支回答之后

当学生提出问题后，Teacher Agent 不再重复 Side Agent 的答案，而是进行教学上的“归位”：

```text
这个问题实际上涉及进程视图和隔离机制。
你刚才看到的现象，是同一个进程在不同 namespace
下呈现了不同的编号。

理解这一点后，再回看当前章节中的容器隔离部分会更容易。
```

它的核心价值是：

> 把一个孤立的问题，重新放回学习路径中。

后续可以增加：

- “你已经掌握了什么”
- “还需要注意什么”
- “接下来建议看哪一节”
- “你可以尝试回答一个小问题”

---

### 4. Side Tutor：旁支问题回答

当前的旁支回答由通用文本流式接口完成，职责是回答：

- 用户当前提出的问题
- 用户对某个概念的追问
- 用户对示例的疑问
- 用户对章节内容的质疑

为了提高质量，Side Tutor 不应该只收到用户当前这一句话，而应该收到一个明确的上下文包：

```text
当前知识卡：
Linux 进程的本质

当前章节：
进程与 namespace

本节目标：
理解不同 namespace 如何影响进程的可见性

白板内容：
...

最近老师引导：
...

当前旁支历史：
用户：...
AI：...
用户：当前问题
```

目前系统的上下文还比较简单，建议优先补充：

- 当前知识卡标题
- 当前章节标题
- 当前章节内容
- 当前章节学习目标
- 当前旁支会话历史
- 最近的老师引导
- 相关笔记

这是提升回答质量最重要的一步。

---

### 5. Diagnosis Agent：学习状态诊断

当前诊断逻辑和 Side Agent 结果结合在一起，返回：

- 是否存在知识断层
- 缺少哪些主题
- 是否需要推荐知识卡

建议后续拆成独立的 Diagnosis Agent，因为“回答问题”和“判断学习状态”是两类不同任务。

诊断结果可以扩展为：

```json
{
  "understanding": "partial",
  "questionType": "prerequisite_gap",
  "hasKnowledgeGap": true,
  "missingTopics": ["Linux PID namespace"],
  "misconceptions": [],
  "relatedToCurrentSection": true,
  "needsTeacherIntervention": true,
  "confidence": 0.91
}
```

可以判断的问题包括：

- 用户是完全不懂，还是只差一个细节
- 用户是否存在错误理解
- 问题是否和当前章节相关
- 是否偏离当前学习目标
- 是否值得生成知识卡
- 是否只需要老师补充一句话

推荐不要仅仅因为出现关键词就生成知识卡，而应综合：

- 是否是必要前置知识
- 是否影响当前理解
- 是否重复出现
- 用户是否明确表示不理解
- 是否可以用一两句话补足

---

### 6. Recommendation Agent：知识断层推荐

目前推荐主要由诊断结果直接产生。建议把它作为独立的推荐能力，负责决定：

```text
知识断层是否值得独立成为学习分支
```

推荐结果应该包含：

```json
{
  "title": "Linux PID namespace",
  "reason": "当前问题依赖这个概念",
  "importance": "high",
  "estimatedEffort": "15-20 分钟",
  "suggestedQuestions": [
    "PID namespace 解决了什么问题？",
    "容器中的 PID 为什么和宿主机不同？"
  ],
  "relation": "prerequisite"
}
```

这样用户在决定创建之前，可以先判断：

- 为什么推荐这个主题
- 它是否真的和当前学习目标有关
- 学习它大概需要多少成本
- 这张知识卡会解决什么问题

推荐项应当持久化，生命周期为：

```text
pending
→ discussing
→ accepted
→ rejected
```

其中 `rejected` 更准确地说是“用户暂不处理”或“用户删除推荐”。

---

### 7. Bridge Agent：知识卡之间的连接

用户创建关联知识卡后，Bridge Agent 负责生成：

```text
新知识卡如何帮助理解原来的章节
```

例如：

```text
理解 PID namespace 后，你就能解释为什么容器内外
看到的进程编号不同。这是容器隔离“进程视图”的基础。
```

后续可以让 Bridge Agent 生成结构化关系：

```json
{
  "relation": "prerequisite",
  "fromCard": "Linux PID namespace",
  "toCard": "容器进程隔离",
  "explanation": "...",
  "returnPath": "学习完后回到主知识卡第 2 节"
}
```

这样关联知识卡就不只是“挂在左侧”，而是真正形成学习路径。

---

## 三、建议的 Agent 调用顺序

### 创建知识卡

```text
用户学习目标
    ↓
Main Agent
    ↓
结构化课程大纲
    ↓
知识卡章节
    ↓
保存课程元数据
```

不要只保存 Markdown，还应该保存：

- 章节目标
- 关键知识点
- 预计难度
- 前置主题
- 常见误区
- 检查问题

---

### 进入章节

```text
用户切换章节
    ↓
加载章节内容
    ↓
加载老师引导历史
    ↓
没有初始引导？
    ↓
Teacher Agent 生成章节导入
```

如果章节已经有历史引导，则直接展示，不要每次重复生成。

---

### 旁支提问

```text
用户问题
    ↓
Context Builder 构建上下文
    ↓
Side Tutor 流式回答
    ↓
保存旁支消息
    ↓
Diagnosis Agent 分析
    ↓
Teacher Agent 生成教学总结
    ↓
Recommendation Agent 判断是否推荐知识卡
```

这里要注意顺序：

- Side Tutor 先给用户即时回答
- Diagnosis 在回答后分析
- Teacher Agent 再从教学角度总结
- Recommendation 最后决定是否生成建议

这样用户不会等待所有分析完成后才看到回答。

---

### 继续讨论推荐主题

```text
点击“继续讨论”
    ↓
创建全新 side conversation
    ↓
写入推荐主题和推荐原因
    ↓
自动发送第一条上下文问题
    ↓
新会话独立回答
```

原会话不追加内容。

新会话可以使用：

```text
当前章节上下文
+ 推荐主题
+ 推荐原因
+ 用户的初始问题
```

但不要把原旁支的全部消息复制过去，避免上下文污染。只需要引用必要摘要。

---

### 创建关联知识卡

```text
用户确认创建
    ↓
Main Agent 生成关联知识卡
    ↓
保存 parentCardId / sourceConversationId
    ↓
Bridge Agent 生成知识桥接
    ↓
推荐状态变为 accepted
    ↓
出现在关联知识卡列表
```

---

## 四、目前最需要提升的地方

### 1. 补齐上下文构建

这是当前最优先的技术工作。

建议增加一个独立的 `ContextBuilder`：

```python
context = context_builder.for_side_conversation(
    card=card,
    section=section,
    conversation=conversation,
    recent_messages=recent_messages,
    guidance=guidance,
    notes=notes,
)
```

统一管理：

- 上下文内容
- 消息长度
- 历史截断
- 当前章节
- 关联知识卡
- 用户笔记

不要由每个 Agent 自己拼接上下文。

---

### 2. Side Agent 和 Diagnosis Agent 解耦

当前旁支回答和诊断能力混在一起，会导致：

- 回复提示词变复杂
- 结构化输出失败时影响回答
- 诊断内容可能泄露给用户
- 难以单独评估回答质量和诊断质量

建议拆成：

```text
Side Tutor：只负责回答
Diagnosis：只负责分析
```

这样旁支可以先正常流式返回，诊断失败也不影响用户看到答案。

---

### 3. 输出全部结构化

所有非聊天型 Agent 都应使用结构化输出：

- Main Agent
- Teacher Agent
- Diagnosis Agent
- Recommendation Agent
- Bridge Agent

并配合：

- JSON Schema
- Pydantic 校验
- 自动重试
- 错误修复
- 最大重试次数
- 失败降级

当前 Provider 层已经有结构化调用基础，可以继续扩展。

---

### 4. 增加教学策略，而不只是角色名称

“老师 Agent”“旁支 Agent”只是角色划分，真正影响效果的是教学策略。

建议使用以下策略：

#### 渐进式解释

不要一次性给出所有知识：

```text
现象 → 直觉解释 → 技术原理 → 示例 → 回到当前章节
```

#### 苏格拉底式追问

在适合的场景不要立即给最终答案：

```text
你觉得容器里的 PID 为什么可能和宿主机不同？
你认为这是创建了新进程，还是改变了进程的视图？
```

#### 错误理解纠正

明确识别：

```text
你当前的理解有一部分是正确的，但需要修正一点……
```

#### 最近发展区

回答难度应该略高于用户当前水平，而不是直接跳到专家级解释。

#### 间隔复习

在章节结束、创建关联卡、重新打开学习空间时，适时提出简短回顾问题。

---

### 5. 增加主动检查，而不只是被动问答

当前模式主要是：

```text
学生阅读 → 学生提问
```

还可以增加：

```text
老师引导 → 学生回答 → 系统判断掌握程度
```

例如每节末尾增加：

```text
想确认一下：
为什么容器里的进程编号可能和宿主机不同？
```

用户回答后，由 Assessment Agent 判断：

```json
{
  "mastery": "partial",
  "correctPoints": ["提到了 namespace"],
  "missingPoints": ["没有说明 PID 视图"],
  "nextAction": "teacher_hint"
}
```

这会比单纯让用户自己点击“下一节”更接近真实教学。

---

## 五、建议的技术架构

```text
Frontend
  ├── 白板渲染
  ├── 老师引导区域
  ├── 旁支会话
  ├── 推荐知识卡
  └── 用户笔记

API / Application Layer
  ├── Learning Orchestrator
  ├── Context Builder
  ├── Conversation Service
  ├── Guidance Service
  ├── Recommendation Service
  └── Learning Progress Service

Agent Layer
  ├── Main Agent
  ├── Teacher Agent
  ├── Side Tutor Agent
  ├── Diagnosis Agent
  ├── Recommendation Agent
  ├── Bridge Agent
  └── Assessment Agent

AI Infrastructure
  ├── Provider Gateway
  ├── Model Router
  ├── Structured Output
  ├── Streaming
  ├── Retry / Fallback
  ├── Token Budget
  └── Prompt Versioning

Persistence
  ├── Knowledge Cards
  ├── Sections
  ├── Conversations
  ├── Messages
  ├── Teacher Guidance
  ├── Recommendations
  ├── Notes
  └── Learning Events
```

## 六、提升教学效果的优先级

我建议按这个顺序推进：

### 第一优先级：提升当前回答质量

- 补充章节和白板上下文
- 加入旁支历史消息
- Side Tutor 与 Diagnosis 解耦
- 统一 Context Builder
- 保证流式回答和诊断互不影响

### 第二优先级：完善老师教学行为

- 老师引导不重复白板
- 根据章节目标生成导入
- 旁支后进行主线归位
- 根据错误理解提供提示
- 支持“继续思考”而不是只给答案

### 第三优先级：加入主动学习

- 章节小测
- 学习掌握度
- 节末回顾
- 错题和薄弱点
- 间隔复习

### 第四优先级：形成个性化学习路径

- 用户知识状态
- 前置知识图谱
- 推荐优先级
- 学习时间成本
- 自动调整章节顺序
- 关联知识卡回流主线

## 最关键的判断

目前最重要的不是继续增加更多 Agent，而是把已有 Agent 的边界和上下文做好：

```text
Main Agent 负责构建课程
Side Tutor 负责回答问题
Diagnosis 负责判断学习状态
Teacher Agent 负责教学引导
Recommendation 负责决定是否需要新知识卡
Bridge Agent 负责连接知识路径
Assessment Agent 负责判断是否学会
```

其中，真正决定教学效果的是：

```text
准确的上下文
+ 清晰的 Agent 边界
+ 合理的教学策略
+ 持续的学习状态
+ 主动检查和反馈
```

建议下一步优先实施 `Context Builder + Side Tutor / Diagnosis 拆分`，这是对现有系统教学效果提升最大的基础工作。
