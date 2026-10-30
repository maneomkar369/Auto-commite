import os
import shutil
from pathlib import Path

from github import Github

from github_utils import clone_branch, get_pr_details
from llm_solver import analyze_and_fix
from push_fix import push_fixes


def _post_comment(pr_number: int, text: str) -> None:
    token = os.getenv("GITHUB_TOKEN")
    owner = os.getenv("REPO_OWNER")
    name = os.getenv("REPO_NAME")

    if not token or not owner or not name:
        raise RuntimeError("Missing GitHub configuration")

    repo = Github(token).get_repo(f"{owner}/{name}")
    repo.get_pull(pr_number).create_issue_comment(text)


async def handle_pull_request(pr_number: int) -> None:
    print(f"Processing PR #{pr_number}...")

    pr_details = get_pr_details(pr_number)
    branch = pr_details["branch"]

    local_path = f"/tmp/repo_{pr_number}"
    clone_branch(branch, local_path)

    try:
        file_contents: dict[str, str] = {}
        for changed_file in pr_details["files"]:
            filename = changed_file["filename"]
            full_path = Path(local_path) / filename
            if full_path.exists() and full_path.is_file():
                file_contents[filename] = full_path.read_text(encoding="utf-8", errors="ignore")

        result = analyze_and_fix(pr_details, file_contents)

        if result.get("has_issues") and result.get("fixed_files"):
            stats = push_fixes(
                pr_number=pr_number,
                branch=branch,
                fixed_files=result["fixed_files"],
                review_comment=result.get("review_comment", "Applied automated fixes."),
            )
            print(f"✅ Fixes pushed for PR #{pr_number}: {stats}")
            return

        _post_comment(pr_number, "🤖 **AI Review:** This PR looks good! No issues found.")
        print(f"✅ No issues found for PR #{pr_number}")
    except Exception as exc:
        error_comment = (
            "🤖 **AI Review:** I hit an internal error while analyzing this PR. "
            "Please retry after checking bot logs."
        )
        try:
            _post_comment(pr_number, error_comment)
        except Exception:
            pass
        print(f"❌ Failed PR #{pr_number}: {exc}")
    finally:
        shutil.rmtree(local_path, ignore_errors=True)
