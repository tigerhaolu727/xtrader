from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from xtrader.backtests import initialize_offline_report_viewer


def test_initialize_offline_report_viewer_copies_assets(tmp_path) -> None:
    output_dir = tmp_path / "viewer"
    outputs = initialize_offline_report_viewer(output_dir=output_dir)

    html_path = Path(outputs["viewer_html_path"])
    echarts_path = Path(outputs["echarts_path"])
    hyparquet_root = Path(outputs["hyparquet_root"])
    hyparquet_bundle_path = Path(outputs["hyparquet_bundle_path"])
    assert html_path.exists()
    assert echarts_path.exists()
    assert hyparquet_root.exists()
    assert (hyparquet_root / "index.js").exists()
    assert hyparquet_bundle_path.exists()

    html = html_path.read_text(encoding="utf-8")
    assert '<script src="./echarts.min.js"></script>' in html
    assert '<script src="./vendor/hyparquet.bundle.js"></script>' in html
    assert 'const api = window.hyparquet;' in html
    assert 'id="manifestFile"' not in html
    assert 'id="timelineMode"' in html
    assert "Signal vs Execution Timeline" in html
    assert "run_manifest.json" in html
    assert "const withinWindow = (rows, keyFn) => {" in html
    assert "state.chunkSets = manifest.chunk_sets || {};" in html
    assert "detectManifestCandidate" in html
    assert "await loadWindowData();" in html


def test_offline_report_viewer_script_init(tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    output_dir = tmp_path / "viewer_cli"
    script = repo_root / "scripts" / "offline_report_viewer.py"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "src")
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "init",
            "--output",
            str(output_dir),
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert (output_dir / "offline_report_viewer.html").exists()
    assert (output_dir / "echarts.min.js").exists()
    assert (output_dir / "vendor" / "hyparquet" / "index.js").exists()
    assert (output_dir / "vendor" / "hyparquet.bundle.js").exists()
    assert "viewer_html_path:" in completed.stdout
    assert "hyparquet_root:" in completed.stdout
    assert "hyparquet_bundle_path:" in completed.stdout
