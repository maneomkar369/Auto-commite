import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from github import Github
from github.GithubException import GithubException, UnknownObjectException

from autonomous_pr import _apply_fixes, _collect_file_context, _run_validation, _to_bool
from llm_solver import analyze_issue_and_generate_fix


def _client() -> Github:
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("Missing GITHUB_TOKEN")
    return Github(token)


def _token() -> str:
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("Missing GITHUB_TOKEN")
    return token


def _resolve_labels(repo: Any, labels: list[str]) -> list[Any]:
    resolved = []
    for label in labels:
        try:
            resolved.append(repo.get_label(label))
        except UnknownObjectException:
            continue
    return resolved


def _fork_labels() -> list[str]:
    raw = os.getenv("FORK_PREFERRED_LABELS", "good first issue,bug")
    return [label.strip() for label in raw.split(",") if label.strip()]


def _clone_fork_branch(fork_full_name: str, base_branch: str, local_path: Path) -> None:
    if local_path.exists():
        shutil.rmtree(local_path)
    clone_url = f"https://{_token()}@github.com/{fork_full_name}.git"
    subprocess.run(
        ["git", "clone", "--depth", "1", "-b", base_branch, clone_url, str(local_path)],
        check=True,
        capture_output=True,
        text=True,
    )


def _git_commit_push(local_path: Path, branch: str, message: str) -> str:
    subprocess.run(["git", "checkout", "-b", branch], cwd=str(local_path), check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.name", os.getenv("AUTONOMOUS_GIT_NAME", "ai-pr-bot")],
        cwd=str(local_path),
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", os.getenv("AUTONOMOUS_GIT_EMAIL", "ai-pr-bot@example.com")],
        cwd=str(local_path),
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(["git", "add", "-A"], cwd=str(local_path), check=True, capture_output=True, text=True)

    status = subprocess.run(["git", "status", "--porcelain"], cwd=str(local_path), check=True, capture_output=True, text=True)
    if not status.stdout.strip():
        raise RuntimeError("No changes to commit")

    subprocess.run(["git", "commit", "-m", message], cwd=str(local_path), check=True, capture_output=True, text=True)
    subprocess.run(["git", "push", "origin", branch], cwd=str(local_path), check=True, capture_output=True, text=True)
    return branch


def _select_or_create_issue(upstream_repo: Any, issue_number: int | None, allow_create_if_missing: bool) -> Any:
    if issue_number is not None:
        issue = upstream_repo.get_issue(number=issue_number)
        if issue.pull_request:
            raise RuntimeError(f"#{issue_number} is a pull request, not an issue")
        if issue.state != "open":
            raise RuntimeError(f"Issue #{issue_number} is not open")
        return issue

    max_issues = int(os.getenv("FORK_MAX_ISSUES", "10"))
    preferred = _resolve_labels(upstream_repo, _fork_labels())

    candidates: list[Any] = []
    for issue in upstream_repo.get_issues(state="open", labels=preferred):
        if issue.pull_request:
            continue
        candidates.append(issue)
        if len(candidates) >= max_issues:
            break

    if not candidates:
        for issue in upstream_repo.get_issues(state="open"):
            if issue.pull_request:
                continue
            candidates.append(issue)
            if len(candidates) >= max_issues:
                break

    if candidates:
        candidates.sort(key=lambda item: item.created_at)
        return candidates[0]

    if not allow_create_if_missing:
        raise RuntimeError("No open issues found")

    title = os.getenv("FORK_BOOTSTRAP_ISSUE_TITLE", "Bug: documentation consistency and typo cleanup")
    body = os.getenv(
        "FORK_BOOTSTRAP_ISSUE_BODY",
        "Automatically created by AI contribution bot because no open issues were available.\n\n"
        "Acceptance criteria:\n"
        "- Small, focused, safe change\n"
        "- No unrelated refactors\n"
        "- Keep style and formatting consistent",
    )

    labels = _resolve_labels(upstream_repo, _fork_labels())
    try:
        return upstream_repo.create_issue(title=title, body=body, labels=labels)
    except GithubException as exc:
        raise RuntimeError(f"No open issues found and unable to create one: {exc}") from exc


def _ensure_fork(client: Github, upstream_repo: Any) -> tuple[Any, str]:
    user = client.get_user()
    fork_owner = user.login

    try:
        fork_repo = client.get_repo(f"{fork_owner}/{upstream_repo.name}")
        return fork_repo, fork_owner
    except GithubException:
        pass

    upstream_repo.create_fork()

    deadline = time.time() + 60
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            fork_repo = client.get_repo(f"{fork_owner}/{upstream_repo.name}")
            return fork_repo, fork_owner
        except GithubException as exc:
            last_error = exc
            time.sleep(2)

    raise RuntimeError(f"Fork was not ready in time: {last_error}")


def run_fork_issue_cycle(
    upstream_owner: str,
    upstream_repo_name: str,
    issue_number: int | None = None,
    dry_run: bool | None = None,
    allow_create_issue_if_missing: bool = True,
) -> dict[str, Any]:
    client = _client()
    upstream_repo = client.get_repo(f"{upstream_owner}/{upstream_repo_name}")
    issue = _select_or_create_issue(upstream_repo, issue_number, allow_create_issue_if_missing)

    fork_repo, fork_owner = _ensure_fork(client, upstream_repo)
    base_branch = upstream_repo.default_branch
    local_path = Path(f"/tmp/fork_issue_{upstream_owner}_{upstream_repo_name}_{issue.number}")
    if dry_run is None:
        dry_run = _to_bool(os.getenv("AUTONOMOUS_DRY_RUN"), default=False)

    _clone_fork_branch(f"{fork_owner}/{fork_repo.name}", base_branch, local_path)

    try:
        context_files = _collect_file_context(local_path, issue.title, issue.body or "")
        llm_result = analyze_issue_and_generate_fix(
            issue_details={
                "number": issue.number,
                "title": issue.title,
                "body": issue.body or "",
                "labels": [label.name for label in issue.labels],
                "repository": f"{upstream_owner}/{upstream_repo_name}",
            },
            file_contents=context_files,
        )

        if not llm_result.get("has_fix"):
            return {
                "status": "no-fix",
                "issue_number": issue.number,
                "message": llm_result.get("summary", "No changes proposed"),
            }

        changed_files = _apply_fixes(local_path, llm_result.get("fixed_files", {}))
        validation = _run_validation(local_path)

        if dry_run:
            return {
                "status": "dry-run",
                "issue_number": issue.number,
                "upstream": f"{upstream_owner}/{upstream_repo_name}",
                "fork": f"{fork_owner}/{fork_repo.name}",
                "changed_files": changed_files,
                "validation": validation,
                "title": llm_result.get("pr_title"),
            }

        if validation["ran"] and not validation["passed"]:
            return {
                "status": "validation-failed",
                "issue_number": issue.number,
                "changed_files": changed_files,
                "validation": validation,
            }

        branch = f"ai/fork-issue-{issue.number}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        _git_commit_push(local_path, branch, f"fix(issue): resolve #{issue.number} with AI")

        require_approval = _to_bool(os.getenv("AUTONOMOUS_REQUIRE_APPROVAL"), default=True)
        pr_title = llm_result.get("pr_title") or f"fix: resolve issue #{issue.number}"
        pr_body = llm_result.get("pr_body") or llm_result.get("summary") or "Automated fix generated by AI bot."

        pull = upstream_repo.create_pull(
            title=pr_title,
            body=f"Closes #{issue.number}\n\n{pr_body}",
            head=f"{fork_owner}:{branch}",
            base=base_branch,
            draft=require_approval,
        )

        close_issue = _to_bool(os.getenv("FORK_CLOSE_ISSUE_AFTER_PR"), default=True)
        if close_issue:
            issue.create_comment(f"Resolved by AI PR: {pull.html_url}")
            issue.edit(state="closed")

        return {
            "status": "pr-created",
            "issue_number": issue.number,
            "pr_number": pull.number,
            "pr_url": pull.html_url,
            "branch": branch,
            "upstream": f"{upstream_owner}/{upstream_repo_name}",
            "fork": f"{fork_owner}/{fork_repo.name}",
            "changed_files": changed_files,
            "validation": validation,
            "issue_closed": close_issue,
        }
    finally:
        shutil.rmtree(local_path, ignore_errors=True)
