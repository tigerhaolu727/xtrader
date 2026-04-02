#!/usr/bin/env python3
"""
Task guard utilities for enforcing Spec + Validation workflow.

Usage:
    python scripts/task_guard.py new TASK_ID --title "Description"
    python scripts/task_guard.py check TASK_ID
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_DIR = REPO_ROOT / "docs" / "03-delivery" / "specs"
VALID_DIR = REPO_ROOT / "docs" / "03-delivery" / "validation"
TEMPLATE_DIR = REPO_ROOT / "docs" / "03-delivery" / "templates"

REQUIRED_SPEC_SECTIONS = ["## Intent", "## Requirement", "## Design", "## Acceptance"]
REQUIRED_VALID_SECTIONS = ["## Planned Validation", "## Execution Log"]


def load_template(name: str) -> str:
    path = TEMPLATE_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Template missing: {path}")
    return path.read_text(encoding="utf-8")


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def cmd_new(task_id: str, title: str | None) -> None:
    title = title or task_id
    spec_path = SPEC_DIR / f"{task_id}.md"
    valid_path = VALID_DIR / f"{task_id}.md"

    if spec_path.exists() or valid_path.exists():
        raise SystemExit(f"Task '{task_id}' already initialized.")

    spec_template = load_template("spec-template.md")
    valid_template = load_template("validation-template.md")

    write_file(spec_path, spec_template.format(task_id=task_id, task_title=title))
    write_file(valid_path, valid_template.format(task_id=task_id))

    print(f"[OK] Created Spec: {spec_path}")
    print(f"[OK] Created Validation Plan: {valid_path}")


def ensure_sections(path: Path, sections: list[str]) -> list[str]:
    missing: list[str] = []
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    for sec in sections:
        if sec not in text:
            missing.append(sec)
    if not text.strip():
        missing.append("non-empty content")
    return missing


def cmd_check(task_id: str) -> None:
    spec_path = SPEC_DIR / f"{task_id}.md"
    valid_path = VALID_DIR / f"{task_id}.md"

    errors: list[str] = []

    if not spec_path.exists():
        errors.append(f"Spec missing: {spec_path}")
    else:
        missing = ensure_sections(spec_path, REQUIRED_SPEC_SECTIONS)
        if missing:
            errors.append(f"Spec incomplete ({spec_path}): missing {', '.join(missing)}")

    if not valid_path.exists():
        errors.append(f"Validation plan missing: {valid_path}")
    else:
        missing = ensure_sections(valid_path, REQUIRED_VALID_SECTIONS)
        if missing:
            errors.append(f"Validation incomplete ({valid_path}): missing {', '.join(missing)}")

    if errors:
        print("✗ Process guard failed:")
        for item in errors:
            print(f"  - {item}")
        raise SystemExit(1)

    print("✓ Spec & Validation check passed.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Spec + Validation guard")
    subparsers = parser.add_subparsers(dest="command", required=True)

    new_parser = subparsers.add_parser("new", help="Create Spec and Validation stubs")
    new_parser.add_argument("task_id")
    new_parser.add_argument("--title", help="Human-friendly task title")

    check_parser = subparsers.add_parser("check", help="Verify Spec & Validation presence")
    check_parser.add_argument("task_id")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "new":
        cmd_new(args.task_id, args.title)
    elif args.command == "check":
        cmd_check(args.task_id)
    else:
        parser.error("Unknown command")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
