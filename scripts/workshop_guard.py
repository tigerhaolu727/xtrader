#!/usr/bin/env python3
"""
Workshop guard utilities for requirement/task/bug discussion docs.

Usage:
    python scripts/workshop_guard.py next-id
    python scripts/workshop_guard.py new XTR-WS-001 --title "..." --type requirement
    python scripts/workshop_guard.py new --auto-id --title "..." --type requirement
    python scripts/workshop_guard.py check XTR-WS-001
    python scripts/workshop_guard.py check XTR-WS-001 --ready
"""

from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSHOP_DIR = REPO_ROOT / "docs" / "03-delivery" / "workshops" / "items"
TEMPLATE_PATH = REPO_ROOT / "docs" / "03-delivery" / "workshops" / "templates" / "workshop-template.md"
INDEX_PATH = REPO_ROOT / "docs" / "03-delivery" / "workshops" / "index.md"

ALLOWED_TYPES = {"requirement", "task", "bug"}
ALLOWED_STATUS = {"draft", "discussing", "review", "approved", "deferred", "rejected"}
ALLOWED_DECISION = {"pending", "approved", "deferred", "rejected"}

REQUIRED_SECTIONS = [
    "Background",
    "Goal / Problem Statement",
    "Scope In",
    "Scope Out",
    "Constraints",
    "Requirement Summary",
    "Acceptance Criteria",
    "Reproduction Steps (BUG required)",
    "Risks",
    "Open Questions",
    "Discussion Log",
    "Quality Gate Checklist",
    "Promotion Decision",
]

SEMANTIC_AMBIGUOUS_TERMS = [
    "尽快",
    "尽量",
    "适当",
    "合理",
    "明显",
    "稳定",
    "高效",
    "必要时",
    "后续再说",
    "somehow",
    "etc",
]

PLACEHOLDER_PATTERNS = [
    r"\bTBD\b",
    r"\bTODO\b",
    r"\?\?\?",
    r"待定",
    r"待补充",
    r"_TBD_",
]


class GuardError(Exception):
    pass


def _iter_existing_ids() -> list[int]:
    ids: list[int] = []
    if WORKSHOP_DIR.exists():
        for path in WORKSHOP_DIR.glob("XTR-WS-*.md"):
            m = re.match(r"^XTR-WS-(\d{3})\.md$", path.name)
            if m:
                ids.append(int(m.group(1)))
        # Backward compatibility for previously generated IDs.
        for path in WORKSHOP_DIR.glob("XTR-BR-*.md"):
            m = re.match(r"^XTR-BR-(\d{3})\.md$", path.name)
            if m:
                ids.append(int(m.group(1)))
    return sorted(set(ids))


def _next_workshop_id() -> str:
    ids = _iter_existing_ids()
    nxt = (ids[-1] + 1) if ids else 1
    if nxt > 999:
        raise GuardError("No available workshop id in range XTR-WS-001..XTR-WS-999")
    return f"XTR-WS-{nxt:03d}"


def _read(path: Path) -> str:
    if not path.exists():
        raise GuardError(f"File missing: {path}")
    return path.read_text(encoding="utf-8")


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _extract_sections(text: str) -> dict[str, str]:
    # Match "## Heading" blocks until next heading.
    pattern = re.compile(r"^##\s+(.+?)\n(.*?)(?=^##\s+|\Z)", re.M | re.S)
    sections: dict[str, str] = {}
    for heading, body in pattern.findall(text):
        sections[heading.strip()] = body.strip()
    return sections


def _extract_meta_value(text: str, key: str) -> str | None:
    # Example: - status: `draft` # comment
    m = re.search(rf"^-\s+{re.escape(key)}:\s+(.+)$", text, re.M)
    if not m:
        return None
    raw = m.group(1)
    raw = raw.split("#", 1)[0].strip()
    if raw.startswith("`") and raw.endswith("`") and len(raw) >= 2:
        raw = raw[1:-1].strip()
    return raw


def _normalize_scope_line(line: str) -> str:
    v = line.strip()
    v = re.sub(r"^-\s*", "", v)
    v = re.sub(r"[`*_]", "", v)
    v = re.sub(r"\s+", " ", v).strip().lower()
    return v


def _extract_bullets(section_text: str) -> list[str]:
    lines: list[str] = []
    for line in section_text.splitlines():
        s = line.strip()
        if s.startswith("-"):
            lines.append(_normalize_scope_line(s))
    return [x for x in lines if x]


def _append_index_row(workshop_id: str, title: str, workshop_type: str, updated: str) -> None:
    text = _read(INDEX_PATH)
    if workshop_id in text:
        return

    row = f"| {workshop_id} | {title} | {workshop_type} | draft | - | {updated} |"
    marker = "## 维护规则"
    if marker in text:
        head, tail = text.split(marker, 1)
        if not head.endswith("\n"):
            head += "\n"
        head += row + "\n\n"
        text = head + marker + tail
    else:
        if not text.endswith("\n"):
            text += "\n"
        text += "\n" + row + "\n"

    _write(INDEX_PATH, text)


def cmd_new(workshop_id: str | None, title: str, workshop_type: str, auto_id: bool) -> None:
    if auto_id and workshop_id:
        raise GuardError("Do not pass workshop_id when --auto-id is set")
    if not auto_id and not workshop_id:
        raise GuardError("workshop_id is required unless --auto-id is set")
    if auto_id:
        workshop_id = _next_workshop_id()
    assert workshop_id is not None

    if not re.match(r"^XTR-WS-\d{3}$", workshop_id):
        raise GuardError("workshop_id must match XTR-WS-XXX, e.g. XTR-WS-001")
    if workshop_type not in ALLOWED_TYPES:
        raise GuardError(f"type must be one of: {sorted(ALLOWED_TYPES)}")

    workshop_path = WORKSHOP_DIR / f"{workshop_id}.md"
    if workshop_path.exists():
        raise GuardError(f"Workshop already exists: {workshop_path}")

    template = _read(TEMPLATE_PATH)
    today = date.today().isoformat()
    content = template.format(
        brief_id=workshop_id,  # backward-compatible template variables
        brief_title=title,
        brief_type=workshop_type,
        workshop_id=workshop_id,
        workshop_title=title,
        workshop_type=workshop_type,
        created_at=today,
    )

    _write(workshop_path, content)
    _append_index_row(workshop_id, title, workshop_type, today)

    print(f"[OK] Created Workshop: {workshop_path}")
    print(f"[OK] Updated Index: {INDEX_PATH}")
    print(f"[OK] Workshop ID: {workshop_id}")


def cmd_next_id() -> None:
    print(_next_workshop_id())


def cmd_check(workshop_id: str, ready: bool) -> None:
    workshop_path = WORKSHOP_DIR / f"{workshop_id}.md"
    # Backward compatibility: if old BR id exists and caller passes WS counterpart, accept it.
    if not workshop_path.exists() and workshop_id.startswith("XTR-WS-"):
        legacy_path = WORKSHOP_DIR / workshop_id.replace("XTR-WS-", "XTR-BR-", 1)
        if legacy_path.exists():
            workshop_path = legacy_path
    text = _read(workshop_path)

    errors: list[str] = []
    warnings: list[str] = []

    # Sections
    sections = _extract_sections(text)
    for sec in REQUIRED_SECTIONS:
        if sec not in sections:
            errors.append(f"Missing section: ## {sec}")

    # Basic metadata
    meta_type = _extract_meta_value(text, "type")
    meta_status = _extract_meta_value(text, "status")
    decision = _extract_meta_value(text, "decision")

    if not meta_type:
        errors.append("Missing metadata: type")
    elif meta_type not in ALLOWED_TYPES:
        errors.append(f"Invalid type: {meta_type}")

    if not meta_status:
        errors.append("Missing metadata: status")
    elif meta_status not in ALLOWED_STATUS:
        errors.append(f"Invalid status: {meta_status}")

    if decision and decision not in ALLOWED_DECISION:
        errors.append(f"Invalid decision: {decision}")

    # Semantic ambiguity checks in core sections
    core_text = "\n".join(
        [
            sections.get("Goal / Problem Statement", ""),
            sections.get("Requirement Summary", ""),
            sections.get("Acceptance Criteria", ""),
        ]
    )
    for term in SEMANTIC_AMBIGUOUS_TERMS:
        if term in core_text:
            errors.append(f"Semantic ambiguity term found: {term}")

    # Placeholder checks
    for pat in PLACEHOLDER_PATTERNS:
        if re.search(pat, core_text, re.I):
            errors.append(f"Unclear placeholder found in core sections: pattern={pat}")

    # Scope conflict check
    scope_in = set(_extract_bullets(sections.get("Scope In", "")))
    scope_out = set(_extract_bullets(sections.get("Scope Out", "")))
    overlap = sorted(x for x in scope_in & scope_out if x not in {"_tbd_", "n/a"})
    if overlap:
        errors.append(f"Scope conflict detected (in/out overlap): {overlap}")

    # Requirement -> acceptance mapping
    req_ids = set(re.findall(r"\bREQ-(\d{3})\b", sections.get("Requirement Summary", "")))
    acc_refs = set(re.findall(r"\(REQ-(\d{3})\)", sections.get("Acceptance Criteria", "")))
    if not req_ids:
        errors.append("Requirement Summary must contain REQ-XXX entries")
    if not acc_refs:
        errors.append("Acceptance Criteria must reference REQ-XXX, e.g. ACC-001 (REQ-001)")
    missing_acc = sorted(req_ids - acc_refs)
    if missing_acc:
        errors.append(f"Requirements without acceptance mapping: {missing_acc}")

    # BUG reproduction completeness
    if meta_type == "bug":
        repro = sections.get("Reproduction Steps (BUG required)", "")
        for key in ["precondition", "steps", "expected", "actual"]:
            m = re.search(rf"^-\s+{key}:\s+(.+)$", repro, re.M)
            if not m:
                errors.append(f"BUG workshop missing reproduction field: {key}")
                continue
            value = m.group(1).strip().strip("`")
            if value.lower() in {"n/a", "_tbd_", "tbd", "todo"}:
                errors.append(f"BUG reproduction field not concrete: {key}")

    # Open question gate
    open_q_lines: list[str] = []
    for line in sections.get("Open Questions", "").splitlines():
        s = line.strip()
        if s.startswith("-") and "Q-" in s:
            open_q_lines.append(s)
    unresolved_q = [ln for ln in open_q_lines if "[Resolved]" not in ln and "[Closed]" not in ln]

    # Ready gate: all checklist items checked + no unresolved questions + approved status/decision
    checklist = sections.get("Quality Gate Checklist", "")
    if ready:
        for item in [
            "Structure complete",
            "No semantic ambiguity",
            "No conflicts (scope/constraints/acceptance)",
            "No unclear descriptions",
            "Open questions resolved",
        ]:
            if not re.search(rf"^-\s+\[x\]\s+{re.escape(item)}$", checklist, re.M | re.I):
                errors.append(f"Ready gate unchecked: {item}")

        if unresolved_q:
            errors.append(f"Ready gate failed: unresolved open questions = {len(unresolved_q)}")

        if meta_status != "approved":
            errors.append("Ready gate failed: status must be `approved`")
        if decision != "approved":
            errors.append("Ready gate failed: decision must be `approved`")
    else:
        if meta_status == "approved" or decision == "approved":
            if unresolved_q:
                errors.append("Approved workshop cannot keep unresolved open questions")

    if unresolved_q and not ready:
        warnings.append(f"Open questions unresolved: {len(unresolved_q)}")

    if errors:
        print("✗ Workshop guard failed:")
        for err in errors:
            print(f"  - {err}")
        if warnings:
            print("! Warnings:")
            for w in warnings:
                print(f"  - {w}")
        raise SystemExit(1)

    if warnings:
        print("✓ Workshop check passed with warnings:")
        for w in warnings:
            print(f"  - {w}")
    else:
        if ready:
            print("✓ Workshop is ready and approved for task development flow.")
        else:
            print("✓ Workshop check passed.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Workshop guard")
    subparsers = parser.add_subparsers(dest="command", required=True)

    new_parser = subparsers.add_parser("new", help="Create a workshop discussion doc")
    new_parser.add_argument("workshop_id", nargs="?", help="e.g. XTR-WS-001")
    new_parser.add_argument("--title", required=True, help="Human-friendly title")
    new_parser.add_argument("--type", required=True, choices=sorted(ALLOWED_TYPES))
    new_parser.add_argument(
        "--auto-id",
        action="store_true",
        help="Auto-allocate the next XTR-WS-XXX id",
    )

    check_parser = subparsers.add_parser("check", help="Validate a workshop discussion doc")
    check_parser.add_argument("workshop_id", help="e.g. XTR-WS-001")
    check_parser.add_argument(
        "--ready",
        action="store_true",
        help="Enable final ready gate (all checks required for promotion)",
    )

    subparsers.add_parser("next-id", help="Print next available workshop id")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "new":
        cmd_new(args.workshop_id, args.title, args.type, args.auto_id)
    elif args.command == "check":
        cmd_check(args.workshop_id, args.ready)
    elif args.command == "next-id":
        cmd_next_id()
    else:
        parser.error("Unknown command")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
