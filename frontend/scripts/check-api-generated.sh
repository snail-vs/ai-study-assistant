#!/usr/bin/env sh
set -eu

npm run api:generate
git diff --exit-code -- src/api/generated/schema.ts
