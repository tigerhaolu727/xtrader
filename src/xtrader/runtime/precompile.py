"""Precompile engine for Runtime Core v1."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from xtrader.runtime.config import ConfigLoader, LoadedRuntimeConfig
from xtrader.runtime.errors import RuntimeContractError
from xtrader.runtime.hash_utils import sha256_hex
from xtrader.strategies.feature_engine.indicators.registry import IndicatorRegistry, build_default_indicator_registry

_MULTI_OUTPUT_SUFFIXES: dict[str, tuple[str, ...]] = {
    "macd": ("line", "signal", "hist"),
    "bollinger": ("mid", "up", "low"),
    "kd": ("k", "d", "j"),
    "dmi": ("plus_di", "minus_di", "adx"),
}
_RULE_ROOT_KEYS: tuple[str, ...] = ("signal_rules", "scoring_rules", "fusion_rules")
_FEATURE_REF_PATTERN = re.compile(r"^[0-9]+[A-Za-z]+\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+$")
_WARN_IMPLICIT_FEATURE_REF = "PC-REF-101"


@dataclass(frozen=True, slots=True)
class PrecompileResult:
    status: str
    catalog_path: str
    report_path: str | None
    error_code: str | None = None
    error_message: str | None = None
    feature_catalog: list[dict[str, Any]] = field(default_factory=list)
    resolved_config: dict[str, Any] = field(default_factory=dict)
    precompile_report: dict[str, Any] = field(default_factory=dict)


class PrecompileEngine:
    """Resolve indicator plan and produce feature catalog."""

    def __init__(
        self,
        *,
        registry: IndicatorRegistry | None = None,
        config_loader: ConfigLoader | None = None,
    ) -> None:
        self.registry = registry or build_default_indicator_registry()
        self.config_loader = config_loader or ConfigLoader()

    def compile(
        self,
        config: dict[str, Any] | str | LoadedRuntimeConfig,
        trial_selector: str | None = None,
    ) -> PrecompileResult:
        loaded = config if isinstance(config, LoadedRuntimeConfig) else self.config_loader.load(config)
        warn_policy = str(loaded.resolved.get("warn_policy", "record_only"))
        trial_mode = str((loaded.resolved.get("trial_config") or {}).get("mode", "single"))
        try:
            selected = self._select_trial(
                loaded=loaded,
                trial_mode=trial_mode,
                trial_selector=trial_selector,
            )
            selected_trial_id = str(selected["trial_id"])
            selected_resolved = selected["resolved_config"]
            feature_catalog, warnings = self._build_feature_catalog(selected_resolved)
            warn_codes = sorted({str(item["code"]) for item in warnings})
            warn_count = int(len(warnings))
            if warnings and warn_policy == "error":
                escalated = dict(warnings[0])
                escalated["severity"] = "ERROR"
                escalated["message"] = f"{escalated['message']} (upgraded by warn_policy=error)"
                return self._build_failed_result(
                    err=RuntimeContractError(
                        code=str(escalated["code"]),
                        stage="precompile",
                        path=str(escalated["path"]),
                        message=str(escalated["message"]),
                        severity="ERROR",
                        timeframe=escalated.get("timeframe"),
                        instance_id=escalated.get("instance_id"),
                        feature_ref=escalated.get("feature_ref"),
                        suggestion=escalated.get("suggestion"),
                    ),
                    warn_policy=warn_policy,
                    resolved_config=loaded.resolved,
                    warnings=warnings,
                )
            report = {
                "stage": "precompile",
                "status": "SUCCESS",
                "warn_count": warn_count,
                "warn_codes": warn_codes,
                "warn_policy": warn_policy,
                "errors": [],
                "warnings": warnings,
                "trial_id": selected_trial_id,
                "feature_count": int(len(feature_catalog)),
            }
            return PrecompileResult(
                status="SUCCESS",
                catalog_path="<in-memory>",
                report_path=None,
                feature_catalog=feature_catalog,
                resolved_config=selected_resolved,
                precompile_report=report,
            )
        except RuntimeContractError as err:
            return self._build_failed_result(
                err=err,
                warn_policy=warn_policy,
                resolved_config=loaded.resolved,
            )

    def _select_trial(
        self,
        *,
        loaded: LoadedRuntimeConfig,
        trial_mode: str,
        trial_selector: str | None,
    ) -> dict[str, Any]:
        trials = self.config_loader.resolve_trials(loaded)
        if trial_mode == "single":
            selector = str(trial_selector).strip() if trial_selector is not None else ""
            if selector not in ("", "single", "baseline"):
                raise RuntimeContractError(
                    code="PC-TRI-001",
                    stage="precompile",
                    path="$.trial_selector",
                    message=f"unknown trial_selector: {selector}",
                )
            return trials[0]

        selector = str(trial_selector).strip() if trial_selector is not None else ""
        if not selector:
            raise RuntimeContractError(
                code="PC-TRI-001",
                stage="precompile",
                path="$.trial_selector",
                message="trial_selector is required when trial_config.mode=scenarios",
            )
        for item in trials:
            if str(item["trial_id"]) == selector:
                return item
        raise RuntimeContractError(
            code="PC-TRI-001",
            stage="precompile",
            path="$.trial_selector",
            message=f"unknown trial_selector: {selector}",
        )

    def _build_failed_result(
        self,
        *,
        err: RuntimeContractError,
        warn_policy: str,
        resolved_config: dict[str, Any],
        warnings: list[dict[str, Any]] | None = None,
    ) -> PrecompileResult:
        warning_items = list(warnings or [])
        report = {
            "stage": "precompile",
            "status": "FAILED",
            "warn_count": int(len(warning_items)),
            "warn_codes": sorted({str(item.get("code", "")) for item in warning_items if str(item.get("code", ""))}),
            "warn_policy": warn_policy,
            "errors": [err.as_dict()],
            "warnings": warning_items,
        }
        return PrecompileResult(
            status="FAILED",
            catalog_path="<in-memory>",
            report_path=None,
            error_code=err.code,
            error_message=err.message,
            feature_catalog=[],
            resolved_config=resolved_config,
            precompile_report=report,
        )

    def _build_feature_catalog(self, resolved_config: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        catalog: list[dict[str, Any]] = []
        indicator_plan_by_tf = resolved_config["indicator_plan_by_tf"]
        for timeframe in sorted(indicator_plan_by_tf.keys()):
            plan = indicator_plan_by_tf[timeframe]
            seen_instance_ids: set[str] = set()
            seen_family_signatures: set[tuple[str, str]] = set()
            for idx, item in enumerate(plan):
                instance_id = str(item["instance_id"]).strip()
                family = str(item["family"]).strip().lower()
                params = dict(item["params"])
                plan_path = f"$.indicator_plan_by_tf.{timeframe}[{idx}]"

                if instance_id in seen_instance_ids:
                    raise RuntimeContractError(
                        code="PC-DUP-001",
                        stage="precompile",
                        path=f"{plan_path}.instance_id",
                        message=f"duplicate instance_id in timeframe {timeframe}: {instance_id}",
                    )
                seen_instance_ids.add(instance_id)

                try:
                    indicator = self.registry.get(family)
                except ValueError as exc:
                    raise RuntimeContractError(
                        code="PC-CFG-003",
                        stage="precompile",
                        path=f"{plan_path}.family",
                        message=str(exc),
                    ) from exc

                try:
                    resolved_params = indicator.resolve_params(params)
                except ValueError as exc:
                    raise RuntimeContractError(
                        code="PC-CFG-003",
                        stage="precompile",
                        path=f"{plan_path}.params",
                        message=str(exc),
                    ) from exc

                family_signature = (family, indicator.build_prefix(resolved_params))
                if family_signature in seen_family_signatures:
                    raise RuntimeContractError(
                        code="PC-DUP-002",
                        stage="precompile",
                        path=plan_path,
                        message=f"duplicate family+params in timeframe {timeframe}: {family_signature[1]}",
                    )
                seen_family_signatures.add(family_signature)

                output_keys = _MULTI_OUTPUT_SUFFIXES.get(family, ("value",))
                if family in _MULTI_OUTPUT_SUFFIXES:
                    physical_cols = indicator.build_output_columns(resolved_params, suffixes=output_keys)
                else:
                    physical_cols = indicator.build_output_columns(resolved_params)
                if len(output_keys) != len(physical_cols):
                    raise RuntimeContractError(
                        code="PC-OUT-001",
                        stage="precompile",
                        path=plan_path,
                        message=f"output key mismatch for family={family}",
                    )

                params_hash = _hash_payload(resolved_params)
                for output_key, physical_col in zip(output_keys, physical_cols):
                    catalog.append(
                        {
                            "feature_ref": f"{timeframe}.{instance_id}.{output_key}",
                            "physical_col": str(physical_col),
                            "timeframe": str(timeframe),
                            "family": family,
                            "instance_id": instance_id,
                            "resolved_params": dict(resolved_params),
                            "params_hash": f"sha256:{params_hash}",
                        }
                    )
        warnings = self._validate_rule_feature_refs(resolved_config=resolved_config, catalog=catalog)
        return catalog, warnings

    def _validate_rule_feature_refs(self, *, resolved_config: dict[str, Any], catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
        refs = self._collect_rule_feature_refs(resolved_config)
        warnings: list[dict[str, Any]] = []
        if not refs:
            return warnings

        catalog_refs = {str(item["feature_ref"]) for item in catalog}
        output_map: dict[tuple[str, str], set[str]] = {}
        for item in catalog:
            feature_ref = str(item["feature_ref"])
            parts = self._split_feature_ref(feature_ref)
            if parts is None:
                continue
            timeframe, instance_id, output_key = parts
            key = (timeframe, instance_id)
            if key not in output_map:
                output_map[key] = set()
            output_map[key].add(output_key)

        for entry in refs:
            feature_ref = entry["feature_ref"]
            path = entry["path"]
            explicit = bool(entry.get("explicit", False))
            if feature_ref in catalog_refs:
                if not explicit:
                    parts = self._split_feature_ref(feature_ref)
                    warnings.append(
                        {
                            "code": _WARN_IMPLICIT_FEATURE_REF,
                            "stage": "precompile",
                            "severity": "WARN",
                            "path": path,
                            "message": f"implicit feature_ref detected: {feature_ref}",
                            "timeframe": parts[0] if parts else None,
                            "instance_id": parts[1] if parts else None,
                            "feature_ref": feature_ref,
                            "suggestion": "use explicit key `feature_ref` for rule references",
                        }
                    )
                continue
            parts = self._split_feature_ref(feature_ref)
            if parts is None:
                raise RuntimeContractError(
                    code="PC-REF-001",
                    stage="precompile",
                    path=path,
                    message=f"invalid feature_ref format: {feature_ref}",
                    feature_ref=feature_ref,
                    suggestion="use {timeframe}.{instance_id}.{output_key}",
                )
            timeframe, instance_id, output_key = parts
            allowed_output_keys = output_map.get((timeframe, instance_id))
            if allowed_output_keys is not None:
                raise RuntimeContractError(
                    code="PC-OUT-001",
                    stage="precompile",
                    path=path,
                    message=f"invalid output_key '{output_key}' for feature_ref {timeframe}.{instance_id}",
                    timeframe=timeframe,
                    instance_id=instance_id,
                    feature_ref=feature_ref,
                    suggestion=f"allowed output_keys: {','.join(sorted(allowed_output_keys))}",
                )
            raise RuntimeContractError(
                code="PC-REF-001",
                stage="precompile",
                path=path,
                message=f"unresolved feature_ref: {feature_ref}",
                timeframe=timeframe,
                instance_id=instance_id,
                feature_ref=feature_ref,
                suggestion="ensure timeframe and instance_id exist in indicator_plan_by_tf",
            )
        return warnings

    def _collect_rule_feature_refs(self, resolved_config: dict[str, Any]) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        for root in _RULE_ROOT_KEYS:
            if root not in resolved_config:
                continue
            refs.extend(self._collect_refs_in_node(resolved_config[root], path=f"$.{root}"))
        return refs

    def _collect_refs_in_node(self, node: Any, *, path: str) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        if isinstance(node, dict):
            for key, value in node.items():
                child_path = f"{path}.{key}"
                if key == "feature_ref" and isinstance(value, str):
                    refs.append({"feature_ref": value.strip(), "path": child_path, "explicit": True})
                refs.extend(self._collect_refs_in_node(value, path=child_path))
            return refs
        if isinstance(node, list):
            for idx, item in enumerate(node):
                refs.extend(self._collect_refs_in_node(item, path=f"{path}[{idx}]"))
            return refs
        if isinstance(node, str):
            value = node.strip()
            if _FEATURE_REF_PATTERN.fullmatch(value):
                refs.append({"feature_ref": value, "path": path, "explicit": False})
        return refs

    def _split_feature_ref(self, value: str) -> tuple[str, str, str] | None:
        text = str(value).strip()
        if not _FEATURE_REF_PATTERN.fullmatch(text):
            return None
        parts = text.split(".")
        if len(parts) != 3:
            return None
        timeframe, instance_id, output_key = parts
        if not timeframe or not instance_id or not output_key:
            return None
        return timeframe, instance_id, output_key


def _hash_payload(payload: dict[str, Any]) -> str:
    return sha256_hex(payload)


__all__ = ["PrecompileEngine", "PrecompileResult"]
