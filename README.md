# Auto-commite

Auto-commite is an AI-powered GitHub automation project that reviews pull requests, identifies fixes, and can autonomously generate and propose code changes using a local LLM workflow.

It supports two core modes:

- PR review automation: listens to pull request webhooks and applies AI-assisted fixes to the relevant branch.
- Autonomous issue-to-PR workflow: finds issues, builds a fix with an LLM, validates the result, and opens a PR.

The project is designed to work well with GitHub repositories you own as well as fork-based contribution workflows for public repositories.

## Why this project exists

Many small engineering teams need a lightweight way to automate repetitive code repair workflows without depending on expensive hosted AI APIs. Auto-commite aims to make that possible using:

- GitHub webhooks and GitHub API access
- FastAPI for the automation service
- Ollama-based local LLM inference
- Temporary repository workspaces for validation and patch generation
- Automated PR creation and issue closure workflows

## Features

- Pull request review handling for GitHub webhook events
- AI-assisted fix generation based on repository context and issue details
- Validation through project tests and local checks before publishing a patch
- Support for direct-repo and fork-based contribution flows
- Background automation endpoints for scheduled or queued runs
- Minimal dependency stack and local-first LLM setup

## Architecture

```text
GitHub Repository
      │
      ▼
GitHub Webhook
      │
      ▼
FastAPI Server
      │
      ├── Handles PR events
      ├── Runs autonomous issue workflows
      ├── Validates code changes
      └── Opens PRs / pushes branches
      │
      ▼
Local LLM (Ollama)
      │
      ▼
GitHub API
```

The system does not require a third-party model provider by default. It can work with a local Ollama instance, which keeps the solution inexpensive and configurable in private environments.

## Repository structure

```text
.
├── autonomous_pr.py         # autonomous issue-to-PR workflow
├── fork_pr.py               # fork-based contribution flow
├── github_utils.py           # GitHub helpers and repo operations
├── handler.py               # pull request event handling
├── llm_solver.py            # LLM prompt / response extraction logic
├── push_fix.py              # push and branch patch logic
├── server.py                # FastAPI app and webhook endpoints
├── requirements.txt         # Python dependencies
├── pytest.ini               # pytest configuration
├── .env.example             # sample environment configuration
├── .gitignore               # ignore rules for local secrets and cache files
├── README.md                # project documentation
├── web/
│   ├── app.js
│   ├── index.html
│   └── styles.css
├── tests/
│   └── test_module_imports.py
└── .venv/                   # local virtual environment (not committed in production use)
```

## Prerequisites

Before running the project, make sure you have:

- Python 3.10+
- Git installed
- A GitHub personal access token with repository write access
- An Ollama instance running locally or on a reachable host
- A public callback URL if using GitHub webhooks from a local machine (for example, through ngrok)

## Setup

1. Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Copy the sample environment file and fill in your values:

```bash
cp .env.example .env
```

4. Update the variables in `.env`:

```env
GITHUB_TOKEN=your_github_token
GITHUB_WEBHOOK_SECRET=your_webhook_secret
REPO_OWNER=your-github-username
REPO_NAME=your-repository

OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=qwen3.5:397b-cloud

AUTONOMOUS_LABELS=bug,enhancement
AUTONOMOUS_MAX_ISSUES=10
AUTONOMOUS_RUN_TESTS=true
AUTONOMOUS_DRY_RUN=false
AUTONOMOUS_REQUIRE_APPROVAL=true
AUTONOMOUS_GIT_NAME=ai-pr-bot
AUTONOMOUS_GIT_EMAIL=ai-pr-bot@example.com
```

5. Ensure the required model is available in Ollama:

```bash
ollama run qwen3.5:397b-cloud
```

## Running the app locally

Start the FastAPI server:

```bash
uvicorn server:app --host 0.0.0.0 --port 8000
```

For public webhook testing with GitHub, expose the local server using a tunnel:

```bash
ngrok http 8000
```

Then use the public URL in your webhook configuration.

## GitHub webhook configuration

In the GitHub repository settings:

- Go to Settings → Webhooks → Add webhook
- Payload URL: `https://<your-public-url>/webhook`
- Content type: `application/json`
- Secret: the same value as `GITHUB_WEBHOOK_SECRET`
- Event type: Pull requests

The app listens for these actions:

- `opened`
- `synchronize`
- `reopened`

## API endpoints

The project exposes a few useful endpoints:

### Health

```bash
curl http://127.0.0.1:8000/health
```

### Run autonomous workflow now

```bash
curl -X POST "http://127.0.0.1:8000/autonomous/run-now"
```

### Run autonomous workflow for a specific issue

```bash
curl -X POST "http://127.0.0.1:8000/autonomous/run-now?issue_number=123"
```

### Queue background automation

```bash
curl -X POST "http://127.0.0.1:8000/autonomous/run?dry_run=true"
```

### Fork-based workflow

```bash
curl -X POST "http://127.0.0.1:8000/autonomous/fork-run?upstream_owner=OWNER&upstream_repo=REPO"
```

## Typical usage flow

### 1. PR review mode

- A pull request is opened or updated.
- GitHub sends a webhook to the service.
- The app analyzes the event and invokes the review and fix logic.
- A patch is generated and pushed back to the PR branch or a temporary branch.

### 2. Autonomous issue mode

- The service fetches open issues.
- It selects a suitable task.
- The LLM proposes a fix.
- The code is validated locally.
- A branch is created and pushed.
- A pull request is opened, and the issue can be closed if configured.

## Security notes

- Never commit secrets or personal access tokens into the repository.
- Keep your `.env` file local and untracked.
- Use GitHub secret scanning and repository protections where possible.
- Prefer using environment variables or secure secret stores in production systems.

## Development notes

- Background tasks are used to process webhook requests quickly.
- Temporary repositories are created under `/tmp` during automation runs and cleaned up after processing.
- The project uses local LLM inference for lower operational cost and easier experimentation.

## Contribution

Contributions are welcome. For a clean workflow:

```bash
git checkout -b feature/my-improvement
# make changes
pytest
git add .
git commit -m "feat: improve automatic fix flow"
git push origin feature/my-improvement
```

## License

This project is licensed under the MIT License. See [LICENSE.md](LICENSE.md) for details.
