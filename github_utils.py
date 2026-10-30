import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from github import Github


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


def get_repo():
    return _client().get_repo(_repo_full_name())


def get_pr_details(pr_number: int) -> dict[str, Any]:
    repo = get_repo()
    pr = repo.get_pull(pr_number)

    changed_files = []
    for changed_file in pr.get_files():
        changed_files.append(
            {
                "filename": changed_file.filename,
                "status": changed_file.status,
                "patch": getattr(changed_file, "patch", None),
                "additions": changed_file.additions,
                "deletions": changed_file.deletions,
            }
        )

    return {
        "title": pr.title,
        "body": pr.body,
        "branch": pr.head.ref,
        "base": pr.base.ref,
        "files": changed_files,
        "comments": [comment.body for comment in pr.get_issue_comments()],
    }


def clone_branch(branch: str, local_path: str) -> str:
    token = os.getenv("GITHUB_TOKEN")
    owner = os.getenv("REPO_OWNER")
    name = os.getenv("REPO_NAME")

    if not token or not owner or not name:
        raise RuntimeError("Missing GitHub configuration")

    target = Path(local_path)
    if target.exists():
        shutil.rmtree(target)

    repo_url = f"https://{token}@github.com/{owner}/{name}.git"
    subprocess.run(
        ["git", "clone", "--depth", "1", "-b", branch, repo_url, str(target)],
        check=True,
        capture_output=True,
        text=True,
    )
    return str(target)
