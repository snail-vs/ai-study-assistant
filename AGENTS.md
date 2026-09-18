# Repository guidance

- For complex, multi-file changes, write an implementation plan before coding. Store it in `.plan/` rather than at the repository root, naming the file `<feature-name>-<YYYYMMDDHHMMSS>.md` (for example, `proposal-id-reliability-20260918174500.md`).
- When `.codegraph/` exists, use CodeGraph before understanding, locating, or editing indexed code.
- Configuration and documentation files that are not indexed may be read directly.
- Use CodeGraph only as an aid for structural analysis; TypeScript/Python compilers and tests determine correctness.
- Do not commit the `.codegraph/` database.
