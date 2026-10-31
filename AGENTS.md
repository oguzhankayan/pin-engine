# pin-engine

Pinterest pins from a link. You (Claude Code) write the plan and review the images; the CLI
reads pages, makes images with Raywake and publishes through Zernio. Follow
`.claude/skills/pin-engine/SKILL.md` for every pin request.

- Run the CLI as `.venv/bin/pin-engine`. Keys live in `.env` (RAYWAKE_API_KEY, ZERNIO_API_KEY).
- Never render (spends money) or publish (cannot be undone) without the user's yes.
- Tests: `.venv/bin/python -m pytest -q`; lint: `.venv/bin/ruff check src tests`.
