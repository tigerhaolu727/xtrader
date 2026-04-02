"""Prepare offline backtest viewer assets."""

from __future__ import annotations

import posixpath
import re
import shutil
from pathlib import Path

_ASSET_ROOT = Path(__file__).resolve().parent / "assets"
_VIEWER_TEMPLATE_NAME = "offline_report_viewer.html"
_ECHARTS_NAME = "echarts.min.js"
_VENDOR_HYPARQUET_DIR = "vendor/hyparquet"
_VENDOR_HYPARQUET_BUNDLE_NAME = "vendor/hyparquet.bundle.js"

_IMPORT_RE = re.compile(r"^\s*import\s+(.+?)\s+from\s+['\"](.+?)['\"]\s*;?\s*$")
_EXPORT_FROM_RE = re.compile(r"^\s*export\s+\{(.+?)\}\s+from\s+['\"](.+?)['\"]\s*;?\s*$")
_EXPORT_STAR_FROM_RE = re.compile(r"^\s*export\s+\*\s+from\s+['\"](.+?)['\"]\s*;?\s*$")
_EXPORT_DECL_RE = re.compile(
    r"^\s*export\s+(async\s+function|function|const|let|var|class)\s+([A-Za-z_$][A-Za-z0-9_$]*)"
)
_EXPORT_NAMED_RE = re.compile(r"^\s*export\s+\{(.+?)\}\s*;?\s*$")


def _resolve_asset(name: str) -> Path:
    path = _ASSET_ROOT / name
    if not path.exists():
        raise FileNotFoundError(f"missing asset: {path}")
    return path


def _copy_asset(*, source: Path, target: Path, overwrite: bool) -> bool:
    if target.exists() and not overwrite:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return True


def _parse_export_specifiers(spec: str) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for token in str(spec).split(","):
        part = token.strip()
        if not part:
            continue
        alias_match = re.match(r"^([A-Za-z_$][A-Za-z0-9_$]*)\s+as\s+([A-Za-z_$][A-Za-z0-9_$]*)$", part)
        if alias_match:
            items.append((alias_match.group(1), alias_match.group(2)))
            continue
        items.append((part, part))
    return items


def _parse_import_spec(spec: str) -> str:
    text = spec.strip()
    if text.startswith("{") and text.endswith("}"):
        names = text[1:-1].strip()
        parts: list[str] = []
        for token in names.split(","):
            item = token.strip()
            if not item:
                continue
            alias_match = re.match(r"^([A-Za-z_$][A-Za-z0-9_$]*)\s+as\s+([A-Za-z_$][A-Za-z0-9_$]*)$", item)
            if alias_match:
                parts.append(f"{alias_match.group(1)}: {alias_match.group(2)}")
            else:
                parts.append(item)
        return "{ " + ", ".join(parts) + " }"
    ns_match = re.match(r"^\*\s+as\s+([A-Za-z_$][A-Za-z0-9_$]*)$", text)
    if ns_match:
        return ns_match.group(1)
    default_and_named_match = re.match(r"^([A-Za-z_$][A-Za-z0-9_$]*)\s*,\s*\{(.+)\}$", text)
    if default_and_named_match:
        default_name = default_and_named_match.group(1)
        named = default_and_named_match.group(2)
        parts: list[str] = [f"default: {default_name}"]
        for token in named.split(","):
            item = token.strip()
            if not item:
                continue
            alias_match = re.match(r"^([A-Za-z_$][A-Za-z0-9_$]*)\s+as\s+([A-Za-z_$][A-Za-z0-9_$]*)$", item)
            if alias_match:
                parts.append(f"{alias_match.group(1)}: {alias_match.group(2)}")
            else:
                parts.append(item)
        return "{ " + ", ".join(parts) + " }"
    return "{ default: " + text + " }"


def _resolve_module_id(*, importer: str, target: str) -> str:
    importer_dir = posixpath.dirname(importer)
    resolved = posixpath.normpath(posixpath.join(importer_dir, target))
    return resolved.removeprefix("./")


def _transform_hyparquet_module(*, module_id: str, source: str) -> str:
    lines = source.splitlines()
    out_lines: list[str] = []
    exports: list[str] = []
    reexport_index = 0
    for line in lines:
        import_match = _IMPORT_RE.match(line)
        if import_match:
            raw_spec, raw_target = import_match.groups()
            dep = _resolve_module_id(importer=module_id, target=raw_target)
            lhs = _parse_import_spec(raw_spec)
            out_lines.append(f"const {lhs} = __require({dep!r});")
            continue

        export_from_match = _EXPORT_FROM_RE.match(line)
        if export_from_match:
            raw_spec, raw_target = export_from_match.groups()
            dep = _resolve_module_id(importer=module_id, target=raw_target)
            reexport_var = f"__reexp{reexport_index}"
            reexport_index += 1
            out_lines.append(f"const {reexport_var} = __require({dep!r});")
            for original, alias in _parse_export_specifiers(raw_spec):
                out_lines.append(f"__exports.{alias} = {reexport_var}.{original};")
            continue

        export_star_match = _EXPORT_STAR_FROM_RE.match(line)
        if export_star_match:
            dep = _resolve_module_id(importer=module_id, target=export_star_match.group(1))
            out_lines.append(f"Object.assign(__exports, __require({dep!r}));")
            continue

        export_decl_match = _EXPORT_DECL_RE.match(line)
        if export_decl_match:
            exports.append(export_decl_match.group(2))
            out_lines.append(line.replace("export ", "", 1))
            continue

        export_named_match = _EXPORT_NAMED_RE.match(line)
        if export_named_match:
            for original, alias in _parse_export_specifiers(export_named_match.group(1)):
                out_lines.append(f"__exports.{alias} = {original};")
            continue

        out_lines.append(line)

    for name in exports:
        out_lines.append(f"__exports.{name} = {name};")
    return "\n".join(out_lines) + "\n"


def _build_hyparquet_browser_bundle(*, source_root: Path, target: Path, overwrite: bool) -> None:
    if target.exists() and not overwrite:
        return
    if not source_root.exists():
        raise FileNotFoundError(f"missing hyparquet source root: {source_root}")

    modules: list[Path] = sorted(source_root.glob("*.js"))
    module_ids: list[str] = [path.name for path in modules if path.name != "node.js"]
    if "index.js" not in module_ids:
        raise FileNotFoundError(f"missing hyparquet entry module: {source_root / 'index.js'}")

    parts: list[str] = [
        "/* Generated for offline file:// usage (no ESM dynamic import). */",
        "(function (global) {",
        '  "use strict";',
        "  const __modules = {};",
    ]
    for module_id in module_ids:
        module_path = source_root / module_id
        transformed = _transform_hyparquet_module(
            module_id=module_id,
            source=module_path.read_text(encoding="utf-8"),
        )
        parts.append(f"  __modules[{module_id!r}] = function (__exports, __require) {{")
        for line in transformed.splitlines():
            parts.append(f"    {line}" if line else "")
        parts.append("  };")
    parts.extend(
        [
            "  const __cache = {};",
            "  function __require(id) {",
            "    if (__cache[id]) return __cache[id].exports;",
            "    const factory = __modules[id];",
            "    if (!factory) throw new Error('Unknown module: ' + id);",
            "    const module = { exports: {} };",
            "    __cache[id] = module;",
            "    factory(module.exports, __require);",
            "    return module.exports;",
            "  }",
            "  global.hyparquet = __require('index.js');",
            "})(typeof globalThis !== 'undefined' ? globalThis : window);",
            "",
        ]
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(parts), encoding="utf-8")


def initialize_offline_report_viewer(
    *,
    output_dir: Path | str,
    html_filename: str = _VIEWER_TEMPLATE_NAME,
    overwrite: bool = True,
) -> dict[str, str]:
    """Copy offline viewer assets into target directory."""
    html_name = str(html_filename).strip() or _VIEWER_TEMPLATE_NAME
    output_root = Path(output_dir).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    viewer_source = _resolve_asset(_VIEWER_TEMPLATE_NAME)
    echarts_source = _resolve_asset(_ECHARTS_NAME)
    hyparquet_source = _resolve_asset(_VENDOR_HYPARQUET_DIR)
    hyparquet_bundle_target = output_root / _VENDOR_HYPARQUET_BUNDLE_NAME
    viewer_target = output_root / html_name
    echarts_target = output_root / _ECHARTS_NAME
    hyparquet_target_root = output_root / "vendor" / "hyparquet"

    _copy_asset(source=viewer_source, target=viewer_target, overwrite=overwrite)
    _copy_asset(source=echarts_source, target=echarts_target, overwrite=overwrite)
    if hyparquet_target_root.exists() and overwrite:
        shutil.rmtree(hyparquet_target_root)
    if overwrite or not hyparquet_target_root.exists():
        hyparquet_target_root.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(hyparquet_source, hyparquet_target_root, dirs_exist_ok=overwrite)
    _build_hyparquet_browser_bundle(
        source_root=hyparquet_source,
        target=hyparquet_bundle_target,
        overwrite=overwrite,
    )

    return {
        "viewer_root": str(output_root),
        "viewer_html_path": str(viewer_target),
        "echarts_path": str(echarts_target),
        "hyparquet_root": str(hyparquet_target_root),
        "hyparquet_bundle_path": str(hyparquet_bundle_target),
    }


__all__ = ["initialize_offline_report_viewer"]
