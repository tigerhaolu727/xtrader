#!/usr/bin/env python3
"""Initialize offline backtest report viewer assets."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xtrader.backtests import initialize_offline_report_viewer  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Initialize offline report viewer assets.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Copy offline viewer assets to target directory.")
    init_parser.add_argument(
        "--output",
        default="reports/backtests/viewer",
        help="target directory for offline viewer assets",
    )
    init_parser.add_argument(
        "--html-name",
        default="offline_report_viewer.html",
        help="viewer html filename in output directory",
    )
    init_parser.add_argument(
        "--no-overwrite",
        action="store_true",
        help="do not overwrite existing files",
    )
    return parser


def _cmd_init(args: argparse.Namespace) -> int:
    outputs = initialize_offline_report_viewer(
        output_dir=Path(str(args.output)),
        html_filename=str(args.html_name),
        overwrite=not bool(args.no_overwrite),
    )
    print(f"viewer_root: {outputs['viewer_root']}")
    print(f"viewer_html_path: {outputs['viewer_html_path']}")
    print(f"decision_trace_viewer_html_path: {outputs['decision_trace_viewer_html_path']}")
    print(f"echarts_path: {outputs['echarts_path']}")
    print(f"hyparquet_root: {outputs['hyparquet_root']}")
    print(f"hyparquet_bundle_path: {outputs['hyparquet_bundle_path']}")
    return 0


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if args.command == "init":
        return _cmd_init(args)
    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
