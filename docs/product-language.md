# StudyCenter 产品语言规范

本文档定义产品界面、领域模型和 Agent 的固定中英文名称。新增功能、接口说明、Prompt 和 UI 文案应优先使用本规范，避免继续混用“白板、旁支、主知识卡、关联卡”等历史称呼。

## 1. 核心领域对象

| 中文名称 | 英文名称 | 代码名称 | 定义 |
| --- | --- | --- | --- |
| 学习空间 | Learning Space | `LearningSpace` | 围绕一个学习目标形成的知识卡、讨论和学习记录集合。 |
| 知识卡 | Knowledge Card | `KnowledgeCard` | 可独立学习和复用的正式课程内容。首页中的所有卡片地位平等。 |
| 章节 | Section | `CardSection` | 知识卡内部具有稳定 ID 的教学单元。 |
| 当前学习路径 | Active Learning Path | runtime state | 用户当前从哪张卡、哪个章节进入，以及下一步返回哪里。它不是知识卡的永久属性。 |
| 学习分支 | Learning Branch | card relation | 从来源章节进入另一张知识卡的学习关系。知识卡本身不永久区分“主卡”和“关联卡”。 |
| 问题讨论 | Question Thread | `Conversation` | 围绕一个具体问题形成的独立讨论线程，可以持续追问。 |
| 前置知识建议 | Prerequisite Suggestion | `RelatedCardProposal` | 诊断到知识断层后生成、等待用户决定的学习建议。 |
| 导师引导 | Mentor Guidance | `TeacherGuidance` | 进入章节或完成答疑后，由课程导师给出的简短方向提示。 |
| 学习笔记 | Learning Note | `Note` | 用户主动记录的个人理解，不由 AI 自动写入。 |
| AI 任务 | AI Run | `AIRun` | 一次 AI 调用的运行状态和失败信息。 |

## 2. 页面区域

| 中文名称 | 英文名称 | 包含内容 |
| --- | --- | --- |
| 学习状态栏 | Learning Status Bar | 学习空间、知识卡、章节、笔记、主题和设置入口。 |
| 学习导航 | Learning Navigator | 章节目录、本节学习分支、前置知识建议。 |
| 课程区 | Lesson Area | 课程内容、章节导航和导师引导。 |
| 课程内容 | Lesson Content | 当前章节的正式教学内容；当前实现为 Markdown。 |
| 章节导航 | Section Navigation | 上一节、当前位置、下一节。 |
| 导师引导 | Mentor Guidance | 课程导师的章节导入和主线归位提示。 |
| 讨论区 | Discussion Panel | 讨论列表、当前问题讨论、消息输入框。 |
| 讨论列表 | Thread List | 当前知识卡下的问题讨论记录。 |
| 学习笔记 | Learning Notes | 笔记列表、创建和编辑界面。 |
| 互动讲解 | Interactive Explanation | 未来用于流程图、关系图、模拟和可交互内容的课程呈现方式。 |

## 3. Agent 名称与边界

| 中文名称 | 英文名称 | 稳定代码 ID | 是否可见 | 职责 |
| --- | --- | --- | ---: | --- |
| 课程设计 Agent | Course Planning Agent | `course_planner` | 否 | 规划知识卡目标和章节结构。第一阶段由现有 Main Agent 兼任。 |
| 内容生成 Agent | Content Authoring Agent | `content_author` | 否 | 生成章节课程内容。第一阶段由现有 Main Agent 兼任。 |
| 课程导师 | Course Mentor | `teacher` | 是 | 章节导入、提炼学习重点、答疑后回到当前学习路径。 |
| 答疑助教 | Q&A Tutor | `side_tutor` | 是 | 对问题给出最小充分回答，不替代正式课程内容。 |
| 学习诊断器 | Learning Diagnostician | `diagnostician` | 否 | 判断问题是否暴露前置知识断层。 |
| 知识桥接器 | Knowledge Bridge Agent | `knowledge_bridge` | 弱展示 | 完成学习分支后，用一句话连接来源章节。 |
| 讨论导演 | Discussion Director | `discussion_director` | 否 | 未来多角色讨论中的发言调度和终止判断。当前版本不启用。 |
| 好奇同学 | Curious Peer | `peer_curiosity` | 是 | 未来从初学者视角提出追问。当前版本不启用。 |
| 质疑同学 | Critical Peer | `peer_challenger` | 是 | 未来提出反例和边界条件。当前版本不启用。 |

历史数据库中的 `teacher` 和 `side_tutor` ID 保持不变，只更新产品显示名称。Agent 的角色与模型解耦，模型继续通过任务路由选择。

## 4. AI 任务名称

| 中文名称 | 英文名称 | 任务 ID |
| --- | --- | --- |
| 课程内容生成 | Knowledge Card Generation | `knowledge_card` |
| 导师引导 | Mentor Guidance | `teacher_guidance` |
| 答疑回复 | Q&A Response | `side_answer` |
| 知识断层诊断 | Knowledge Gap Diagnosis | `gap_diagnosis` |
| 知识桥接 | Knowledge Bridge | `bridge_note` |
| 会话标题 | Conversation Title | `conversation_title` |
| 多角色调度 | Discussion Direction | `group_director` |

旧任务 `side_agent` 仅用于兼容已有模型路由，不再作为新界面选项。

## 5. 固定交互用语

- 使用“课程内容”，不再使用“Markdown 白板”。
- 使用“问题讨论”，不再使用“旁支会话”。
- 使用“新建讨论”，不再使用“新旁支”。
- 使用“本节学习分支”，不再把知识卡永久称为“关联知识卡”。
- 使用“返回来源知识卡”，不使用“返回主知识卡”。
- 使用“前置知识建议”，不使用“待处理推荐”或“推荐知识卡”。
- “当前学习路径”只描述用户此刻的运行状态，不作为数据对象类型。

## 6. 课堂输出约束

- 答疑助教默认输出 80～200 个中文字符，最多三个要点；用户明确要求展开时才增加内容。
- 课程导师在答疑后只输出 30～80 个中文字符，说明问题与当前章节的关系以及下一步关注点，不复述助教答案。
- 学习诊断器不直接发言，只产生结构化诊断和前置知识建议。
- 知识桥接器只输出一句话。
- 课程内容可以系统完整；即时课堂发言必须短、单一职责、渐进展开。
