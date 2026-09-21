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
