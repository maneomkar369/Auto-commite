import json
import os
import re
from typing import Any

import requests


def _model_name() -> str:
    return os.getenv("OLLAMA_MODEL", "qwen3.5:397b-cloud")


def _ollama_url() -> str:
    return os.getenv("OLLAMA_URL", "http://localhost:11434")


def _chat_json(prompt: str) -> dict[str, Any]:
    response = requests.post(
        f"{_ollama_url().rstrip('/')}/api/chat",
        json={
            "model": _model_name(),
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        },
        timeout=180,
    )
    response.raise_for_status()
    data = response.json()

    raw = (data.get("message") or {}).get("content", "").strip()
    if not raw:
        raise ValueError("Ollama returned an empty response")

    return _extract_json(raw)


def build_prompt(pr_details: dict[str, Any], file_contents: dict[str, str]) -> str:
    files_text = ""
    for filename, content in file_contents.items():
        files_text += f"\n\n--- FILE: {filename} ---\n{content}"

    diffs_text = ""
    for changed_file in pr_details["files"]:
        if changed_file.get("patch"):
            diffs_text += f"\n\n--- DIFF: {changed_file['filename']} ---\n{changed_file['patch']}"

    return f"""You are a senior software engineer reviewing a pull request.

PR Title: {pr_details['title']}
PR Description: {pr_details['body'] or 'No description provided'}

## Changed Files (Diffs)
{diffs_text}

## Full File Contents
{files_text}

## Existing Discussion
{chr(10).join(pr_details.get('comments', [])) or 'No prior comments'}

## Task
1. Identify all bugs, issues, or improvements needed in this PR.
2. Provide the COMPLETE corrected file content for each file that needs changes.
3. Write a clear PR review comment explaining what you fixed and why.

## Response Format (JSON only)
{{
  "review_comment": "Your explanation here...",
  "fixed_files": {{
    "path/to/file.py": "complete corrected file content here",
    "path/to/other.py": "complete corrected file content here"
  }},
  "has_issues": true
}}"""


def _extract_json(raw: str) -> dict[str, Any]:
    raw = raw.strip()

    if raw.startswith("{") and raw.endswith("}"):
        return json.loads(raw)

    code_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if code_block:
        return json.loads(code_block.group(1))

    bracket_match = re.search(r"\{.*\}", raw, re.DOTALL)
    if bracket_match:
        return json.loads(bracket_match.group())

    raise ValueError("LLM did not return valid JSON")


def analyze_and_fix(pr_details: dict[str, Any], file_contents: dict[str, str]) -> dict[str, Any]:
    prompt = build_prompt(pr_details, file_contents)
    return _chat_json(prompt)


def build_issue_prompt(issue_details: dict[str, Any], file_contents: dict[str, str]) -> str:
    files_text = ""
    for filename, content in file_contents.items():
        files_text += f"\n\n--- FILE: {filename} ---\n{content}"

    return f"""You are a senior software engineer implementing a fix for a GitHub issue.

Issue #{issue_details['number']}: {issue_details['title']}
Issue Description: {issue_details.get('body') or 'No description provided'}
Labels: {', '.join(issue_details.get('labels', [])) or 'none'}

## Repository Context (selected files)
{files_text}

## Task
1. Determine whether a safe, production-ready fix can be generated from the available context.
2. If yes, provide complete updated file contents for each file to change.
3. Provide a concise PR title and PR body.
4. Keep fixes minimal, maintainable, and backward-compatible.

## Response Format (JSON only)
{{
  "has_fix": true,
  "summary": "What was fixed and why",
  "pr_title": "fix: ...",
  "pr_body": "Detailed explanation, testing notes, and risks",
  "fixed_files": {{
    "path/to/file.py": "full file content"
  }}
}}"""


def analyze_issue_and_generate_fix(issue_details: dict[str, Any], file_contents: dict[str, str]) -> dict[str, Any]:
    prompt = build_issue_prompt(issue_details, file_contents)
    return _chat_json(prompt)
