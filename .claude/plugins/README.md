# Project-scoped Claude plugins

This project includes local plugins under `.claude/plugins/`.

Installed plugins:

- `frontend-design`
  - Source: `anthropics/claude-plugins-official`
  - Repo stars: ~7.5k
  - Why: official high-quality plugin; useful when improving `monitor.html` UI.

- `modern-python`
  - Source: `trailofbits/skills`
  - Repo stars: ~2.7k
  - Why: aligns with this Python + `uv` project workflow.

- `insecure-defaults`
  - Source: `trailofbits/skills`
  - Repo stars: ~2.7k
  - Why: helps detect insecure fallbacks/secrets in env-based config.

Notes:

- These are vendored copies for project scope usage.
- To keep them updated, re-sync from upstream repositories.
