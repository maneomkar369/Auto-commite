import hashlib
import hmac
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import requests

from autonomous_pr import run_autonomous_ensure_issue_cycle, run_autonomous_issue_cycle
from fork_pr import run_fork_issue_cycle
from handler import handle_pull_request

load_dotenv()
app = FastAPI(title="AI PR Review Bot")
WEB_DIR = Path(__file__).parent / "web"
app.mount("/web", StaticFiles(directory=WEB_DIR), name="web")


class AuthConfigRequest(BaseModel):
    github_token: str
    model_api_key: str | None = None
    ollama_url: str | None = None
    ollama_model: str | None = None


def verify_signature(payload: bytes, signature: str) -> bool:
    secret = os.getenv("GITHUB_WEBHOOK_SECRET")
    if not secret or not signature:
        return False

    expected = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/auth/status")
def auth_status() -> dict:
    return {
        "github_token_set": bool(os.getenv("GITHUB_TOKEN")),
        "model_api_key_set": bool(os.getenv("MODEL_API_KEY") or os.getenv("ANTHROPIC_API_KEY")),
        "ollama_url": os.getenv("OLLAMA_URL", "http://localhost:11434"),
        "ollama_model": os.getenv("OLLAMA_MODEL", "qwen3.5:397b-cloud"),
    }


@app.post("/auth/config")
def auth_config(payload: AuthConfigRequest) -> dict:
    token = payload.github_token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="github_token is required")

    try:
        response = requests.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=20,
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to verify GitHub token: {exc}") from exc

    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid GitHub token")

    user_data = response.json()

    os.environ["GITHUB_TOKEN"] = token
    if payload.model_api_key is not None:
        model_key = payload.model_api_key.strip()
        if model_key:
            os.environ["MODEL_API_KEY"] = model_key
            os.environ["ANTHROPIC_API_KEY"] = model_key
    if payload.ollama_url:
        os.environ["OLLAMA_URL"] = payload.ollama_url.strip()
    if payload.ollama_model:
        os.environ["OLLAMA_MODEL"] = payload.ollama_model.strip()

    return {
        "status": "ok",
        "github_user": user_data.get("login"),
        "message": "Credentials configured in runtime environment",
        "github_token_set": True,
        "model_api_key_set": bool(os.getenv("MODEL_API_KEY") or os.getenv("ANTHROPIC_API_KEY")),
    }


@app.get("/")
def home() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/favicon.ico")
def favicon() -> Response:
    return Response(status_code=204)


def _run_autonomous_safe(issue_number: int | None = None, dry_run: bool | None = None) -> dict:
    try:
        return run_autonomous_issue_cycle(issue_number=issue_number, dry_run=dry_run)
    except Exception as exc:
        print(f"❌ Autonomous run failed: {exc}")
        return {
            "status": "error",
            "issue_number": issue_number,
            "error": str(exc),
        }


def _run_autonomous_ensure_safe(issue_number: int | None = None, dry_run: bool | None = None) -> dict:
    try:
        return run_autonomous_ensure_issue_cycle(issue_number=issue_number, dry_run=dry_run)
    except Exception as exc:
        print(f"❌ Autonomous ensure-run failed: {exc}")
        return {
            "status": "error",
            "issue_number": issue_number,
            "error": str(exc),
        }


def _run_fork_safe(
    upstream_owner: str,
    upstream_repo: str,
    issue_number: int | None = None,
    dry_run: bool | None = None,
    allow_create_issue_if_missing: bool = True,
) -> dict:
    try:
        return run_fork_issue_cycle(
            upstream_owner=upstream_owner,
            upstream_repo_name=upstream_repo,
            issue_number=issue_number,
            dry_run=dry_run,
            allow_create_issue_if_missing=allow_create_issue_if_missing,
        )
    except Exception as exc:
        print(f"❌ Fork run failed: {exc}")
        return {
            "status": "error",
            "issue_number": issue_number,
            "error": str(exc),
            "upstream": f"{upstream_owner}/{upstream_repo}",
        }


@app.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks) -> dict:
    payload_bytes = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")

    if not verify_signature(payload_bytes, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    event = request.headers.get("X-GitHub-Event", "")
    payload = json.loads(payload_bytes)

    if event == "pull_request" and payload.get("action") in {"opened", "synchronize", "reopened"}:
        pr_number = payload["pull_request"]["number"]
        background_tasks.add_task(handle_pull_request, pr_number)

    return {"status": "ok"}


@app.post("/autonomous/run")
async def autonomous_run(
    background_tasks: BackgroundTasks,
    issue_number: int | None = None,
    dry_run: bool | None = None,
) -> dict:
    background_tasks.add_task(_run_autonomous_safe, issue_number, dry_run)
    return {
        "status": "queued",
        "issue_number": issue_number,
        "dry_run": dry_run,
    }


@app.post("/autonomous/run-now")
async def autonomous_run_now(issue_number: int | None = None, dry_run: bool | None = None) -> dict:
    result = _run_autonomous_safe(issue_number=issue_number, dry_run=dry_run)
    return {"status": "ok", "result": result}


@app.post("/autonomous/ensure-run")
async def autonomous_ensure_run(
    background_tasks: BackgroundTasks,
    issue_number: int | None = None,
    dry_run: bool | None = None,
) -> dict:
    background_tasks.add_task(_run_autonomous_ensure_safe, issue_number, dry_run)
    return {
        "status": "queued",
        "issue_number": issue_number,
        "dry_run": dry_run,
        "ensure_issue": True,
    }


@app.post("/autonomous/ensure-run-now")
async def autonomous_ensure_run_now(issue_number: int | None = None, dry_run: bool | None = None) -> dict:
    result = _run_autonomous_ensure_safe(issue_number=issue_number, dry_run=dry_run)
    return {"status": "ok", "result": result}


@app.post("/autonomous/fork-run")
async def autonomous_fork_run(
    background_tasks: BackgroundTasks,
    upstream_owner: str,
    upstream_repo: str,
    issue_number: int | None = None,
    dry_run: bool | None = None,
    allow_create_issue_if_missing: bool = True,
) -> dict:
    background_tasks.add_task(
        _run_fork_safe,
        upstream_owner,
        upstream_repo,
        issue_number,
        dry_run,
        allow_create_issue_if_missing,
    )
    return {
        "status": "queued",
        "upstream": f"{upstream_owner}/{upstream_repo}",
        "issue_number": issue_number,
        "dry_run": dry_run,
        "allow_create_issue_if_missing": allow_create_issue_if_missing,
    }


@app.post("/autonomous/fork-run-now")
async def autonomous_fork_run_now(
    upstream_owner: str,
    upstream_repo: str,
    issue_number: int | None = None,
    dry_run: bool | None = None,
    allow_create_issue_if_missing: bool = True,
) -> dict:
    result = _run_fork_safe(
        upstream_owner=upstream_owner,
        upstream_repo=upstream_repo,
        issue_number=issue_number,
        dry_run=dry_run,
        allow_create_issue_if_missing=allow_create_issue_if_missing,
    )
    return {"status": "ok", "result": result}
