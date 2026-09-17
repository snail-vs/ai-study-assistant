# StudyCenter 模型任务路由

## 设计原则

模型不绑定 Agent，而绑定稳定的教学任务。Agent 负责角色、提示词、权限和行为；Gateway 根据 task 选择模型。这样同一个教师 Agent 可以在生成课程、章节引导和问题诊断时使用不同模型。

任务路由是全局配置，不属于某一个 Provider。Provider 设置只负责保存某家的 Key 和已选模型；任务路由可以从所有已配置 Provider 中选择模型。

## 设置页模型分工

设置页默认不直接展示内部任务清单，而是提供一个全局默认模型和三个可选角色模型：

| 设置项 | 覆盖的任务 |
| --- | --- |
| 课程设计与内容生成 | `course_plan`、`section_content`、`section_repair`、`quiz_generation` |
| 质量审查与知识诊断 | `section_review`、`quiz_evaluation`、`gap_diagnosis` |
| 课堂实时互动 | `teacher_guidance`、`side_answer`、`side_answer_plan`、`bridge_note`、`conversation_title`、`group_director` |

三项均可留空并继承全局默认模型。需要为单个任务使用不同模型时，才展开“高级任务路由”进行覆盖；单项覆盖优先于角色模型。

## 当前任务

| task | 用途 |
| --- | --- |
| `course_plan` | 课程规划 |
| `section_content` | 章节内容生成 |
| `section_review` | 章节质量审查 |
| `section_repair` | 章节内容修订 |
| `quiz_generation` | 理解检查生成 |
| `quiz_evaluation` | 理解检查评估 |
| `teacher_guidance` | 章节进入和旁支问题后的教师引导 |
| `side_answer` | 课程讨论中的答疑回复 |
| `side_answer_plan` | 答疑的篇幅、形式与教学策略规划 |
| `gap_diagnosis` | 知识断层诊断 |
| `bridge_note` | 生成关联知识卡之间的连接说明 |
| `conversation_title` | 会话标题 |
| `group_director` | 未来多 Agent 群聊调度 |

## 解析规则

```text
单项任务覆盖
  ↓ 未配置
所属模型分工
  ↓ 未配置
全局默认模型
```

task route 必须引用设置页中已选的模型。Provider 切换时，Provider 自身负责根据模型解析 API 协议，任务路由不直接维护协议。

## 接口

- `GET /api/v1/settings/model-routes`：返回任务目录和当前模型
- `PUT /api/v1/settings/model-routes`：更新全局任务路由
- `PUT /api/v1/settings/providers/{provider}`：保存指定 Provider 的凭证和可用模型

任务路由保存在 `task_model_routes`，值格式为 `provider:model`，例如 `deepseek:deepseek-chat`。旧版 Provider 的 `task_routes_json` 仅作为兼容回退，不再作为新的存储位置。

## 后续扩展

后续可为路由增加 thinking、超时、降级策略和观测字段，但不建议第一阶段自动学习或隐式切换模型。课程生成等结构化任务应优先保证质量，旁支问答才适合配置更快、更便宜的模型。
