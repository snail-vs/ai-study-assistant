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
