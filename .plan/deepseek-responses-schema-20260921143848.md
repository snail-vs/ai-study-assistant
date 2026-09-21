# DeepSeek Responses structured output

1. Route direct DeepSeek requests through `/responses` so structured tasks use its JSON Schema format instead of Chat Completions JSON mode.
2. Do not send the OpenAI-specific `strict` flag to DeepSeek Responses; preserve JSON-mode fallback with the in-band schema prompt.
3. Detect incomplete or failed Responses before attempting JSON parsing, and cover routing, payload, fallback, and response-status behavior with unit tests.
