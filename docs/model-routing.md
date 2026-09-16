# StudyCenter 模型任务路由

## 设计原则

模型不绑定 Agent，而绑定稳定的教学任务。Agent 负责角色、提示词、权限和行为；Gateway 根据 task 选择模型。这样同一个教师 Agent 可以在生成课程、章节引导和问题诊断时使用不同模型。

任务路由是全局配置，不属于某一个 Provider。Provider 设置只负责保存某家的 Key 和已选模型；任务路由可以从所有已配置 Provider 中选择模型。

## 当前任务

| task | 用途 |
| --- | --- |
| `knowledge_card` | 生成知识卡和章节内容 |
| `teacher_guidance` | 章节进入和旁支问题后的教师引导 |
| `side_agent` | 旁支问答与知识断层诊断 |
| `bridge_note` | 生成关联知识卡之间的连接说明 |
| `conversation_title` | 会话标题 |
| `group_director` | 未来多 Agent 群聊调度 |

## 解析规则

```text
task route
  ↓ 未配置
当前 Provider 的默认模型
```

task route 必须引用设置页中已选的模型。Provider 切换时，Provider 自身负责根据模型解析 API 协议，任务路由不直接维护协议。

## 接口

- `GET /api/v1/settings/model-routes`：返回任务目录和当前模型
- `PUT /api/v1/settings/model-routes`：更新当前 Provider 的任务路由
- `PUT /api/v1/settings/providers/{provider}`：保存 Provider 时可同时提交全局 `taskRoutes`

任务路由保存在 `task_model_routes`，值格式为 `provider:model`，例如 `deepseek:deepseek-chat`。旧版 Provider 的 `task_routes_json` 仅作为兼容回退，不再作为新的存储位置。

## 后续扩展

后续可为路由增加 thinking、超时、降级策略和观测字段，但不建议第一阶段自动学习或隐式切换模型。课程生成等结构化任务应优先保证质量，旁支问答才适合配置更快、更便宜的模型。
