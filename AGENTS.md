# AGENTS.md

This repository is the AI-tooling meta module for `hwmonitor-mqtt`.

## Repository layout

- AI tooling/config stays in this root module:
  - `.claude/`
  - `.mcp.json`
  - `AGENTS.md`
- Product/application source code lives in git submodule:
  - `hwmonitor-core/`

## Working rule

- If the task is about application code, work inside `hwmonitor-core/`.
- Keep AI tooling/config changes in this root module only.
- Do not duplicate application source files into this root module.

## Language requirement

- Replies to users must be in Traditional Chinese (zh-TW), except for code, commands, and identifiers.
