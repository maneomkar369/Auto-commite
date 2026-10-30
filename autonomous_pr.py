import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from github import Github
from github.GithubException import UnknownObjectException

from llm_solver import analyze_issue_and_generate_fix


ALLOWED_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".java",
    ".go",
    ".rs",
    ".md",
    ".json",
    ".yml",
    ".yaml",
}


def _client() -> Github:
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("Missing GITHUB_TOKEN")
    return Github(token)


def _repo_full_name() -> str:
    owner = os.getenv("REPO_OWNER")
    name = os.getenv("REPO_NAME")
    if not owner or not name:
        raise RuntimeError("Missing REPO_OWNER or REPO_NAME")
    return f"{owner}/{name}"


def _repo_url_with_token() -> str:
    token = os.getenv("GITHUB_TOKEN")
    owner = os.getenv("REPO_OWNER")
    name = os.getenv("REPO_NAME")
    if not token or not owner or not name:
        raise RuntimeError("Missing GitHub configuration")
    return f"https://{token}@github.com/{owner}/{name}.git"


def _to_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _labels() -> list[str]:
    raw = os.getenv("AUTONOMOUS_LABELS", "bug,enhancement")
    return [label.strip() for label in raw.split(",") if label.strip()]


def _resolve_labels(repo: Any, labels: list[str]) -> list[Any]:
    resolved_labels = []
    for label in labels:
        try:
            resolved_labels.append(repo.get_label(label))
        except UnknownObjectException:
            continue
    return resolved_labels


def _repo_clone(base_branch: str, local_path: Path) -> None:
    if local_path.exists():
        shutil.rmtree(local_path)
    subprocess.run(
        ["git", "clone", "--depth", "1", "-b", base_branch, _repo_url_with_token(), str(local_path)],
        check=True,
        capture_output=True,
        text=True,
    )


def _keywords(text: str) -> list[str]:
    words = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}", text.lower())
    stop_words = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "issue",
        "error",
        "fails",
        "when",
        "should",
        "into",
        "after",
    }
    return [word for word in words if word not in stop_words][:30]


def _collect_file_context(local_path: Path, issue_title: str, issue_body: str, max_files: int = 25) -> dict[str, str]:
    keys = set(_keywords(f"{issue_title}\n{issue_body or ''}"))
    matched: list[tuple[int, Path]] = []

    for file_path in local_path.rglob("*"):
        if not file_path.is_file():
            continue
        if ".git" in file_path.parts or "node_modules" in file_path.parts:
            continue
        if file_path.suffix.lower() not in ALLOWED_EXTENSIONS:
            continue
        try:
            rel = file_path.relative_to(local_path).as_posix().lower()
        except ValueError:
            continue
        score = sum(1 for key in keys if key in rel)
        matched.append((score, file_path))

    matched.sort(key=lambda item: item[0], reverse=True)
    selected = matched[:max_files]

    file_contents: dict[str, str] = {}
    for _, path in selected:
        rel_path = path.relative_to(local_path).as_posix()
        try:
            file_contents[rel_path] = path.read_text(encoding="utf-8", errors="ignore")[:20000]
        except Exception:
            continue
    return file_contents


def _apply_fixes(local_path: Path, fixed_files: dict[str, str]) -> list[str]:
    changed: list[str] = []
    for rel_path, content in fixed_files.items():
        if not isinstance(content, str):
            continue
        abs_path = (local_path / rel_path).resolve()
        if not str(abs_path).startswith(str(local_path.resolve())):
            continue
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(content, encoding="utf-8")
        changed.append(rel_path)
    return changed


def _run_validation(local_path: Path) -> dict[str, Any]:
    run_tests = _to_bool(os.getenv("AUTONOMOUS_RUN_TESTS"), default=True)
    if not run_tests:
        return {"ran": False, "passed": True, "command": None, "output": "skipped"}

    command: list[str] | None = None
    if (local_path / "pytest.ini").exists() or (local_path / "pyproject.toml").exists() or (local_path / "tests").exists():
        command = ["pytest", "-q"]
    elif (local_path / "package.json").exists():
        command = ["npm", "test", "--", "--watch=false"]

    if not command:
        return {"ran": False, "passed": True, "command": None, "output": "no test command detected"}

    proc = subprocess.run(command, cwd=str(local_path), capture_output=True, text=True)
    output = f"{proc.stdout}\n{proc.stderr}".strip()[:10000]
    return {
        "ran": True,
        "passed": proc.returncode == 0,
        "command": " ".join(command),
        "output": output,
    }


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


def _select_issue(issue_number: int | None, allow_create_if_missing: bool = False) -> Any:
    repo = _client().get_repo(_repo_full_name())
    if issue_number is not None:
        issue = repo.get_issue(number=issue_number)
        if issue.pull_request:
            raise RuntimeError(f"#{issue_number} is a pull request, not an issue")
        if issue.state != "open":
            raise RuntimeError(f"Issue #{issue_number} is not open")
        return repo, issue

    max_issues = int(os.getenv("AUTONOMOUS_MAX_ISSUES", "10"))
    labels = _labels()
    resolved_labels = _resolve_labels(repo, labels)

    candidates: list[Any] = []
    for issue in repo.get_issues(state="open", labels=resolved_labels):
        if issue.pull_request:
            continue
        candidates.append(issue)
        if len(candidates) >= max_issues:
            break

    if not candidates:
        for issue in repo.get_issues(state="open"):
            if issue.pull_request:
                continue
            candidates.append(issue)
            if len(candidates) >= max_issues:
                break

    if not candidates:
        if not allow_create_if_missing:
            raise RuntimeError("No open issues found")

        title = os.getenv(
            "AUTONOMOUS_BOOTSTRAP_ISSUE_TITLE",
            "Bug: improve startup docs consistency",
        )
        body = os.getenv(
            "AUTONOMOUS_BOOTSTRAP_ISSUE_BODY",
            "Automatically created by AI bot because no open issues were present.\n\n"
            "Acceptance criteria:\n"
            "- Apply a minimal safe improvement\n"
            "- Keep changes focused and production-ready\n"
            "- Avoid unrelated refactors",
        )

        created_issue = repo.create_issue(
            title=title,
            body=body,
            labels=resolved_labels,
        )
        return repo, created_issue

    candidates.sort(key=lambda item: item.created_at)
    return repo, candidates[0]


def run_autonomous_issue_cycle(issue_number: int | None = None, dry_run: bool | None = None) -> dict[str, Any]:
    repo, issue = _select_issue(issue_number, allow_create_if_missing=False)
    base_branch = repo.default_branch
    local_path = Path(f"/tmp/autonomous_issue_{issue.number}")
    if dry_run is None:
        dry_run = _to_bool(os.getenv("AUTONOMOUS_DRY_RUN"), default=False)

    _repo_clone(base_branch, local_path)
    try:
        context_files = _collect_file_context(local_path, issue.title, issue.body or "")
        llm_result = analyze_issue_and_generate_fix(
            issue_details={
                "number": issue.number,
                "title": issue.title,
                "body": issue.body or "",
                "labels": [label.name for label in issue.labels],
            },
            file_contents=context_files,
        )

        if not llm_result.get("has_fix"):
            return {
                "status": "no-fix",
                "issue_number": issue.number,
                "message": llm_result.get("summary", "No changes proposed"),
            }

        fixed_files = llm_result.get("fixed_files", {})
        changed_files = _apply_fixes(local_path, fixed_files)
        validation = _run_validation(local_path)

        if dry_run:
            return {
                "status": "dry-run",
                "issue_number": issue.number,
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

        branch = f"ai/issue-{issue.number}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        _git_commit_push(local_path, branch, f"fix(issue): resolve #{issue.number} with AI")

        require_approval = _to_bool(os.getenv("AUTONOMOUS_REQUIRE_APPROVAL"), default=True)
        pr_title = llm_result.get("pr_title") or f"fix: resolve issue #{issue.number}"
        pr_body = llm_result.get("pr_body") or llm_result.get("summary") or "Automated fix generated by AI bot."

        pull = repo.create_pull(
            title=pr_title,
            body=f"Closes #{issue.number}\n\n{pr_body}",
            head=branch,
            base=base_branch,
            draft=require_approval,
        )

        return {
            "status": "pr-created",
            "issue_number": issue.number,
            "pr_number": pull.number,
            "pr_url": pull.html_url,
            "branch": branch,
            "changed_files": changed_files,
            "validation": validation,
        }
    finally:
        shutil.rmtree(local_path, ignore_errors=True)


def run_autonomous_ensure_issue_cycle(issue_number: int | None = None, dry_run: bool | None = None) -> dict[str, Any]:
    repo, issue = _select_issue(issue_number, allow_create_if_missing=True)
    base_branch = repo.default_branch
    local_path = Path(f"/tmp/autonomous_issue_{issue.number}")
    if dry_run is None:
        dry_run = _to_bool(os.getenv("AUTONOMOUS_DRY_RUN"), default=False)

    _repo_clone(base_branch, local_path)
    try:
        context_files = _collect_file_context(local_path, issue.title, issue.body or "")
        llm_result = analyze_issue_and_generate_fix(
            issue_details={
                "number": issue.number,
                "title": issue.title,
                "body": issue.body or "",
                "labels": [label.name for label in issue.labels],
            },
            file_contents=context_files,
        )

        if not llm_result.get("has_fix"):
            return {
                "status": "no-fix",
                "issue_number": issue.number,
                "message": llm_result.get("summary", "No changes proposed"),
            }

        fixed_files = llm_result.get("fixed_files", {})
        changed_files = _apply_fixes(local_path, fixed_files)
        validation = _run_validation(local_path)

        if dry_run:
            return {
                "status": "dry-run",
                "issue_number": issue.number,
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

        branch = f"ai/issue-{issue.number}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        _git_commit_push(local_path, branch, f"fix(issue): resolve #{issue.number} with AI")

        require_approval = _to_bool(os.getenv("AUTONOMOUS_REQUIRE_APPROVAL"), default=True)
        pr_title = llm_result.get("pr_title") or f"fix: resolve issue #{issue.number}"
        pr_body = llm_result.get("pr_body") or llm_result.get("summary") or "Automated fix generated by AI bot."

        pull = repo.create_pull(
            title=pr_title,
            body=f"Closes #{issue.number}\n\n{pr_body}",
            head=branch,
            base=base_branch,
            draft=require_approval,
        )

        close_issue = _to_bool(os.getenv("AUTONOMOUS_CLOSE_ISSUE_AFTER_PR"), default=True)
        if close_issue:
            issue.create_comment(f"Resolved by AI PR: {pull.html_url}")
            issue.edit(state="closed")

        return {
            "status": "pr-created",
            "issue_number": issue.number,
            "pr_number": pull.number,
            "pr_url": pull.html_url,
            "branch": branch,
            "changed_files": changed_files,
            "validation": validation,
            "issue_closed": close_issue,
        }
    finally:
        shutil.rmtree(local_path, ignore_errors=True)
