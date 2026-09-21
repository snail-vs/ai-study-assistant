# JSON-mode structured output hardening

1. Add a provider-neutral prompt supplement that exposes the requested JSON Schema whenever a compatible provider can only enforce `json_object` mode.
2. Make course-outline response fields required so missing output is rejected during parsing rather than silently becoming an empty outline.
3. Add adapter-level and outline-level regression coverage for JSON-mode requests, then run the affected backend test suite.
