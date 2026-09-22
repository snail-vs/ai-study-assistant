# Course generation completion reconciliation

1. Add a backend reconciliation helper that recognizes a course whose persisted sections all contain usable generated content, activates its root card, and clears the failed learning-space state while retaining a quality-review warning.
2. Use that helper when a late course-review/repair step throws, so optional post-generation failures do not leave a fully generated course marked failed.
3. Reconcile legacy failed rows when learning spaces are listed, so existing homepage failure notices disappear without requiring another retry.
4. Add regression coverage for both late review failure and legacy-state reconciliation, then run the focused backend tests.
