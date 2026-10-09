# AI Provider 兼容层

Agent 只描述业务任务和 Pydantic 输出结构，不感知具体 Provider 的请求协议。

```text
Agent schema
  → AIGateway
  → capability profile
  → protocol adapter
  → provider/model
```

当前兼容层支持：

- OpenAI Chat Completions；
- OpenAI Responses；
- Responses strict JSON Schema；
- JSON Object 降级；
- 普通 JSON 文本降级。

严格结构化输出要求所有对象属性出现在 `required` 中，因此业务 Schema 的可选值应使用 nullable 表达。动态 key 字典不适合作为跨 Provider 的结构化输出，优先使用带稳定 ID 的数组。

Provider 原始错误保留在日志和 `details.reason` 中，同时归类为稳定类别：`insufficient_balance`、`authentication`、`rate_limited`、`schema_incompatible`、`unsupported_protocol` 和 `provider_unavailable`。

## 模型列表发现

模型名称可以直接由用户手动输入；手动模型会优先作为请求模型。需要补充候选项时，按以下顺序尝试：Provider 定义的专用模型目录 URL、通用的 `{base_url}/models`。目录接口不存在或返回不兼容格式时，界面保留手动输入流程，不会阻止 Provider 保存。

智谱使用两个独立 Provider：`glm`（中国大陆，`https://open.bigmodel.cn/api/paas/v4`）和 `zai`（海外，`https://api.z.ai/api/paas/v4`）。两者均通过 OpenAI-compatible 的 `/chat/completions` 调用，但 API Key 与可用模型应分别配置。

## 讨论回答断流与手动重试

讨论的最后一轮回答如果未完成，界面保留已收到的内容并标记“回答未完成”，错误提示中提供“重新生成回答”。点击后重新请求完整答案，不是从半句话继续拼接；原问题、之前的完整对话和输入框草稿保持不变。服务端接受重试后才替换该轮残缺回答，生成期间禁止重复提交；再次失败仍可重试。

刷新页面或重新进入讨论时，通过 `GET /conversations/{conversation_id}/runs/latest` 恢复失败状态及 `retryable`、`questionMessageId`、`answerMessageId`。`POST /conversations/{conversation_id}/runs/{run_id}/retry` 不需要请求体，复用原运行与原问题，返回相同的 SSE 消息流。仅最新一轮在 waiting/planning/answering 阶段失败或过期时可重试；回答已完成后的导师引导或知识诊断失败不会替换完整答案。进行中的请求不能并发重试；超过 180 秒未更新的运行恢复为过期状态时保留原阶段。

ChatGPT Codex 必须收到 `response.completed` 才视为完整回答；正常 EOF 但缺少完成事件也按断流处理。应用不会自动重试已输出部分文字的请求，避免无提示地重复生成或混合两次回答。已有失败记录无需数据库迁移即可恢复重试入口。
