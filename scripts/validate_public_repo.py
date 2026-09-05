#!/usr/bin/env python3
"""CI guard for public-repository hygiene and safe defaults."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {
    ".py", ".md", ".txt", ".json", ".js", ".css", ".html",
    ".yml", ".yaml", ".toml", ".ini", ".ps1",
}
TEXT_NAMES = {".gitignore", ".gitattributes", ".editorconfig", ".env.example", "Dockerfile"}
FORBIDDEN_PREFIXES = ("data/", "backups/")
FORBIDDEN_NAMES = {
    "accounts.json", "browser_sessions.json", "oauth_tokens.json", "cookies.json",
}

SECRET_PATTERNS = {
    "generic sk key": re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    "GitHub token": re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    "Google API key": re.compile(r"AIza[0-9A-Za-z_-]{30,}"),
    "Slack token": re.compile(r"xox[baprs]-[A-Za-z0-9-]{20,}"),
    "Bearer token": re.compile(r"Bearer\s+[A-Za-z0-9._-]{24,}"),
    "private key": re.compile(r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY"),
    "Windows user path": re.compile(r"C:\\Users\\[^\\\s]+", re.I),
}


def tracked_files() -> list[str]:
    out = subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=ROOT,
    )
    return [p.decode("utf-8") for p in out.split(b"\0") if p]


def is_text_file(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES or path.name in TEXT_NAMES


def check_public_defaults(issues: list[str]) -> None:
    path = ROOT / "config.example.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("search_only_mode") is not True:
        issues.append("config.example.json must default to search_only_mode=true")
    for key in (
        "merge_saved_searches", "auto_resume_search_enabled", "merge_favorited_vacancies",
        "related_vacancies_enabled", "auto_apply_tests", "llm_enabled", "llm_auto_send",
        "llm_generate_cover_letter", "llm_fill_questionnaire",
    ):
        if data.get(key) is not False:
            issues.append(f"config.example.json must default {key}=false")
    for key in ("daily_apply_limit", "run_apply_limit"):
        value = data.get(key)
        if not isinstance(value, int) or value <= 0:
            issues.append(f"config.example.json must have a positive {key}")


def main() -> int:
    issues: list[str] = []
    for rel in tracked_files():
        normalized = rel.replace("\\", "/")
        if normalized.startswith(FORBIDDEN_PREFIXES) or Path(rel).name in FORBIDDEN_NAMES:
            issues.append(f"forbidden tracked private file: {rel}")
        path = ROOT / rel
        if not path.is_file() or not is_text_file(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            issues.append(f"non-UTF-8 text file {rel}: {exc}")
            continue
        if "\ufffd" in text:
            issues.append(f"replacement character found in {rel}")
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                issues.append(f"{label} found in {rel}")

    try:
        check_public_defaults(issues)
    except Exception as exc:
        issues.append(f"config.example.json validation failed: {exc}")

    if issues:
        print("Public repository validation FAILED:")
        for issue in issues:
            print(f" - {issue}")
        return 1
    print("Public repository validation OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
