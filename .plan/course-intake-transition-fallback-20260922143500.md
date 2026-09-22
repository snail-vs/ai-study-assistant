# Course intake transition fallback

1. Treat an AI response that advances to the next intake stage but omits its question as a recoverable protocol omission.
2. Supply the existing server-owned fallback question for that next stage.
3. Cover the recovery in the state-machine tests and rerun the focused suite.
