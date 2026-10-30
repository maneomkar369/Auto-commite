# AI PR Review + Autonomous PR Generator

FastAPI service with two modes:

- PR review mode: listens to pull request webhooks and pushes AI-assisted fixes to PR branches.
- Autonomous mode: scans open issues, generates fixes via LLM, validates, pushes a branch, and opens a PR.

- Your own repos → push branch directly + open PR
- Other public repos → fork → fix → open PR to original
- LLM → Ollama running Mistral locally (zero API cost)

## Architecture

GitHub Webhook → FastAPI Server → LLM API → GitHub API → Pull Request

Autonomous Mode: Issues → Context Builder → LLM Fix Generator → Validation → Branch/Commit/Push → Pull Request

## 1) Prerequisites

- Python 3.10+
- GitHub personal access token with repo write access
- Ollama running locally or remotely
- Public callback URL (e.g., ngrok in local dev)

## 2) Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill `.env` values:

- `GITHUB_TOKEN`
- `GITHUB_WEBHOOK_SECRET`
- `REPO_OWNER`
- `REPO_NAME`
- `OLLAMA_URL` (optional, default: `http://localhost:11434`)
- `OLLAMA_MODEL` (optional, default: `qwen3.5:397b-cloud`)
- `AUTONOMOUS_LABELS` (default: `bug,enhancement`)
- `AUTONOMOUS_MAX_ISSUES` (default: `10`)
- `AUTONOMOUS_RUN_TESTS` (default: `true`)
- `AUTONOMOUS_DRY_RUN` (default: `false`)
- `AUTONOMOUS_REQUIRE_APPROVAL` (default: `true`, creates draft PRs)
- `AUTONOMOUS_GIT_NAME` / `AUTONOMOUS_GIT_EMAIL` (commit identity)

Start Ollama and ensure your model is available:

```bash
ollama run qwen3.5:397b-cloud
```

## 3) Run locally

```bash
uvicorn server:app --host 0.0.0.0 --port 8000
```

Expose with ngrok:

```bash
ngrok http 8000
```

## 4) Configure GitHub Webhook

Repository → Settings → Webhooks → Add webhook

- Payload URL: `https://<your-public-url>/webhook`
- Content type: `application/json`
- Secret: same as `GITHUB_WEBHOOK_SECRET`
- Events: **Pull requests**

## 5) Trigger events

The bot processes PR actions:

- `opened`
- `synchronize`
- `reopened`

## 6) Run autonomous issue → PR flow

Run once synchronously (returns full result):

```bash
curl -X POST "http://127.0.0.1:8000/autonomous/run-now"
```

Run specific issue number:

```bash
curl -X POST "http://127.0.0.1:8000/autonomous/run-now?issue_number=123"
```

Queue as background task:

```bash
curl -X POST "http://127.0.0.1:8000/autonomous/run?dry_run=true"
```

Create issue if none exists, solve it, and close it after PR creation:

```bash
curl -X POST "http://127.0.0.1:8000/autonomous/ensure-run-now"
```

Background mode for the same workflow:

```bash
curl -X POST "http://127.0.0.1:8000/autonomous/ensure-run"
```

## 7) Contribute to other people's repos (fork workflow)

This mode follows standard GitHub contribution flow:

1. Fork upstream repo to your account
2. Clone your fork and create branch
3. Generate AI fix for selected/open issue
4. Commit + push to fork
5. Open PR from fork branch to upstream default branch
6. Optionally close issue after PR creation

Run synchronously:

```bash
curl -X POST "http://127.0.0.1:8000/autonomous/fork-run-now?upstream_owner=OWNER&upstream_repo=REPO"
```

Run in dry-run mode:

```bash
curl -X POST "http://127.0.0.1:8000/autonomous/fork-run-now?upstream_owner=OWNER&upstream_repo=REPO&dry_run=true"
```

Queue background run:

```bash
curl -X POST "http://127.0.0.1:8000/autonomous/fork-run?upstream_owner=OWNER&upstream_repo=REPO"
```

## Notes

- The handler runs in FastAPI background tasks to return webhook responses quickly.
- The branch clone is temporary (`/tmp/repo_<pr_number>`) and cleaned after processing.
- If the LLM returns no issues, the bot posts a positive review comment.

## Next enhancements

- Queue orchestration (Celery + Redis)
- Diff-only context selection for lower token usage
- Sandbox execution in Docker
- Risk scoring and policy gates before PR creation
- CI status-aware retries and feedback loop
