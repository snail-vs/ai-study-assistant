# Direct retry for failed course generation

1. Add a learning-store action that calls the existing failed-generation retry endpoint with the saved course brief, scale, and outline.
2. Change failed-space actions to emit a direct retry event and show queued-generation feedback instead of reopening course intake.
3. Add store/component regression coverage and run the affected frontend tests.
4. Restrict the DeepSeek Responses route and default model to the currently supported `deepseek-flash` and `deepseek-v4-pro` models.
