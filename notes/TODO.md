# Internal notes — not part of the public README

## Security

- [ ] **Regenerate the GitHub PAT after submission.** It currently holds `repo, workflow` — elevated beyond the
      `public_repo` the running system needs — and has lived in `.env` on a machine where an agent runs commands.
      `.env` is gitignored and verified never committed (2026-09-13: `git log --all --full-history -- .env` empty,
      no token string in the working tree or in any history blob), but elevated scope in an agent-accessible file
      should not outlive the reason for it. After submission: revoke, reissue with `public_repo` only, update
      `.env` and the `FLAKEGUARD_GH_TOKEN` repo secret.
      Why it was raised: the REST workflow-dispatch endpoint returned 500 on a `public_repo` token, so manual CI
      dispatch was impossible. The scheduled runs never needed it — GitHub's scheduler fires the cron, and the
      workflow's writes only need `public_repo`.
- [ ] **Rotate the Bedrock API key after submission** for the same reason.

## Deferred work

- [ ] `explain` converts to percentages ("98% of the time") where the rule is to quote numbers as given. Harmless
      in prose and arithmetically correct, but it is the one place a model still computes. Either tighten the
      prompt or teach the checker to accept a derived percentage that matches its source.

- [ ] Node 20 deprecation warnings on `actions/checkout`, `actions/cache`, `actions/upload-artifact`, `setup-uv`.
      Cosmetic; the runner forced Node 24 and the run succeeded. Bump action majors when convenient.
- [ ] Correlation examines the latest failing commit, not the onset commit (see README limitations).
- [ ] Truncated-artifact detection: flag a run-cell whose testcase count is far below that cell's norm.
