import os
from typing import Any

from github import Github
from github.GithubException import GithubException, UnknownObjectException



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


def push_fixes(pr_number: int, branch: str, fixed_files: dict[str, str], review_comment: str) -> dict[str, Any]:
    repo = _client().get_repo(_repo_full_name())
    pr = repo.get_pull(pr_number)

    updated = 0
    created = 0
    skipped = 0

    for filepath, new_content in fixed_files.items():
        if not isinstance(new_content, str):
            skipped += 1
            continue

        try:
            existing = repo.get_contents(filepath, ref=branch)
            repo.update_file(
                path=filepath,
                message=f"fix: AI-suggested fix for PR #{pr_number}",
                content=new_content,
                sha=existing.sha,
                branch=branch,
            )
            updated += 1
        except UnknownObjectException:
            repo.create_file(
                path=filepath,
                message=f"fix: AI-created file for PR #{pr_number}",
                content=new_content,
                branch=branch,
            )
            created += 1
        except GithubException as exc:
            skipped += 1
            print(f"Failed to push {filepath}: {exc}")

    summary = f"Updated: {updated}, Created: {created}, Skipped: {skipped}"
    pr.create_issue_comment(
        f"🤖 **AI Code Review**\n\n{review_comment}\n\n"
        f"*{updated + created} file(s) updated automatically. {summary}*"
    )

    return {"updated": updated, "created": created, "skipped": skipped}
