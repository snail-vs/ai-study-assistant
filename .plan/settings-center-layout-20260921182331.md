# Application settings center layout

## Objective

Replace the narrow, vertically stacked model-settings dialog with an application-level settings center. Keep AI/model configuration as one expandable settings area while preserving every existing provider, OAuth, model-selection, and routing action.

## Layout

- Wide two-column shell (`~1040px`, bounded by viewport).
- Fixed primary navigation on the left. The initial implemented entry is `AI 与模型`; future settings groups can be added without changing the shell.
- AI content on the right with four horizontal tabs:
  - 模型服务
  - 默认模型
  - 模型分工
  - 高级路由
- Only the active tab renders its controls, removing the current long mixed-purpose scroll.
- Right content scrolls independently; headers and action areas remain visually stable.
- Mobile collapses the primary navigation into a compact top selector and uses horizontally scrollable AI tabs.

## Behavior preservation

- Provider/API-key configuration and model discovery remain on 模型服务.
- ChatGPT OAuth actions remain on 模型服务.
- Global model selection moves to 默认模型.
- Role-level routes move to 模型分工.
- Task-level routes move to 高级路由.
- Provider save and model-assignment save remain separate actions.
- No backend/API contract changes.

## Verification

- Add component tests for primary navigation, AI tabs, manual-model emission, and separated save actions.
- Run frontend unit tests, typecheck, and lint for touched files.
- Run `git diff --check`.
