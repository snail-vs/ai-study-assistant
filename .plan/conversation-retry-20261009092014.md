# 会话失败轮次重试

## 目标
讨论中未完成的最后一轮回答提供“重新生成回答”入口。保留原问题，替换该轮残缺回答，重新运行回答与后续引导；刷新页面后仍能发现失败并重试。不会自动重试，也不会复制用户问题或拼接两次生成的文本。

## 接口与状态
- 将 `GET /conversations/{conversation_id}/runs/active` 切换为 `/runs/latest`，返回最后一次运行（包括失败/完成）。在现有 AIRunResponse 上增加 `retryable`、`questionMessageId`、`answerMessageId`；无运行返回 null。
- 新增 `POST /conversations/{conversation_id}/runs/{run_id}/retry`，无请求体，返回与发送消息一致的 SSE。
- 仅最后一轮 `side_message` 在 waiting/planning/answering 阶段失败或过期可重试。完整回答后的导师/诊断失败不替换回答。通过现有运行和消息时间顺序关联原问题及残缺回答，不改数据库结构，兼容已经产生的失败记录。
- 重用原 run 和 user message；条件更新 failed/expired -> running 防重复提交。校验会话归属、章节、最新轮次及活跃运行。只在接受重试后删除该轮残缺回答，历史完整回答不变。
- `run.started` 提供原问题 ID 和被替换回答 ID；`message.started` 的 ID 与持久化答案一致；`run.failed` 提供运行 ID、阶段及重试资格。断开流时保存残缺回答并标记失败。

## 实施范围
1. 后端会话 API/服务/schema、现有契约与生命周期回归：最新失败状态恢复、无 delta/部分 delta 的重试、反复失败、完整历史保留、拒绝旧轮次/并发/跨用户请求。
2. 前端会话 store/App：共用 SSE 读取逻辑；失败提示与重新生成按钮，残缺回答标识，发送中禁用重试；重试不改输入框、不添加问题；切换会话后旧流不污染当前会话；刷新恢复资格。更新受影响测试与调用方。
3. Codex 流结束必须有正常完成事件，否则认定未完成，避免正常 EOF 被误当成功；完成事件后结束读取。
4. 更新 OpenAPI 与生成类型；运行现有相关测试、类型检查，使用本地真实 UI 和可控断流上游验证失败 -> 点击重试 -> 完成，以及刷新后的失败恢复。验证后补充已有文档说明，不部署或修改生产会话。
