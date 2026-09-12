# FlakeGuard

Autonomous flaky-test triage agent for GitHub Actions + pytest, built on the Strands Agents SDK.

**The determinism boundary:** the LLM reasons; it never carries a fact or a number. All statistics
are computed in Python and pinned into prompts as ground truth. Scheduling, idempotency, deduplication
and rate limiting live in code, not in the model.

## Setup

```sh
uv sync
cp .env.example .env   # fill in GITHUB_TOKEN + AWS creds
uv run scripts/check_bedrock.py
```

`dry_run = true` in `flakeguard.toml` until you point it at a scratch repo you own.

## License

MIT — see [LICENSE](LICENSE).
