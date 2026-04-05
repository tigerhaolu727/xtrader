"""Signal engine runtime for strategy profile v0.3."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

_REQUIRED_SCORING_COLUMNS: tuple[str, ...] = ("timestamp", "symbol", "score_total", "state")


def _xtr_sp005_error(code: str, detail: str) -> ValueError:
    return ValueError(f"XTRSP005::{code}::{detail}")


def _to_float(value: Any) -> float:
    if value is None:
        return float("nan")
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _score_in_range(score: float, score_range: dict[str, Any]) -> bool:
    if pd.isna(score):
        return False
    lower = score_range.get("min")
    upper = score_range.get("max")
    lower_inc = bool(score_range.get("min_inclusive", True))
    upper_inc = bool(score_range.get("max_inclusive", False))

    if lower is not None:
        lower_v = float(lower)
        if lower_inc:
            if score < lower_v:
                return False
        elif score <= lower_v:
            return False
    if upper is not None:
        upper_v = float(upper)
        if upper_inc:
            if score > upper_v:
                return False
        elif score >= upper_v:
            return False
    return True


def _state_allowed(state: str, rule: dict[str, Any]) -> bool:
    deny = rule.get("state_deny")
    if deny is not None and state in set(str(item) for item in deny):
        return False
    allow = rule.get("state_allow")
    if allow is not None and state not in set(str(item) for item in allow):
        return False
    return True


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y", "on"}


def _gate_side_from_action(action: str) -> str | None:
    raw = str(action).upper()
    if raw == "ENTER_LONG":
        return "LONG"
    if raw == "ENTER_SHORT":
        return "SHORT"
    return None


@dataclass(frozen=True, slots=True)
class SignalEngineResult:
    frame: pd.DataFrame


class SignalEngine:
    """Evaluate signal rules and produce one action per row."""

    def run(
        self,
        *,
        resolved_profile: dict[str, Any],
        scoring_df: pd.DataFrame,
    ) -> SignalEngineResult:
        missing = [column for column in _REQUIRED_SCORING_COLUMNS if column not in scoring_df.columns]
        if missing:
            raise _xtr_sp005_error("MISSING_INPUT_COLUMN", ",".join(missing))

        signal_spec = dict(resolved_profile["signal_spec"])
        rules = self._collect_enabled_rules(signal_spec=signal_spec)
        entry_gate_spec = dict(signal_spec.get("entry_gate_spec") or {})
        entry_gates_enabled = bool(entry_gate_spec.get("enabled", False))
        entry_gates = [dict(item) for item in list(entry_gate_spec.get("gates") or [])] if entry_gates_enabled else []
        reason_code_map = {str(k): str(v) for k, v in dict(signal_spec.get("reason_code_map") or {}).items()}
        cooldown_bars = int(signal_spec.get("cooldown_bars", 0))
        cooldown_scope = str(signal_spec.get("cooldown_scope", "symbol_action"))
        if cooldown_bars < 0:
            raise _xtr_sp005_error("COOLDOWN_INVALID", str(cooldown_bars))
        if cooldown_scope != "symbol_action":
            raise _xtr_sp005_error("COOLDOWN_SCOPE_UNSUPPORTED", cooldown_scope)

        enabled_ids = [str(rule["id"]) for rule in rules]
        missing_reason = [rule_id for rule_id in enabled_ids if rule_id not in reason_code_map]
        if missing_reason:
            raise _xtr_sp005_error("MISSING_REASON_CODE_MAPPING", ",".join(missing_reason))

        ordered_index = scoring_df.sort_values(["timestamp", "symbol"]).index.tolist()
        last_fire_by_symbol_action: dict[tuple[str, str], int] = {}
        rows: dict[Any, dict[str, Any]] = {}

        for pos, idx in enumerate(ordered_index):
            row = scoring_df.loc[idx]
            score = _to_float(row["score_total"])
            state = str(row["state"])
            symbol = str(row["symbol"])
            condition_results = dict(row.get("condition_results") or {})
            gate_results = self._evaluate_entry_gates(
                gates=entry_gates,
                condition_results=condition_results,
            )
            selected: dict[str, Any] | None = None
            selected_gate_id: str | None = None

            for rule in rules:
                if not _score_in_range(score, dict(rule["score_range"])):
                    continue
                if not _state_allowed(state, rule):
                    continue
                action = str(rule["action"])
                gate_side = _gate_side_from_action(action)
                if gate_side is not None and entry_gates_enabled:
                    side_gates = [item for item in gate_results if str(item.get("side", "")).upper() == gate_side]
                    if side_gates:
                        passed = [item for item in side_gates if bool(item.get("passed"))]
                        if not passed:
                            continue
                        selected_gate_id = str(passed[0].get("gate_id", "")) or None
                if cooldown_bars > 0 and action != "HOLD":
                    key = (symbol, action)
                    prev = last_fire_by_symbol_action.get(key)
                    if prev is not None and (pos - prev) <= cooldown_bars:
                        continue
                selected = rule
                break

            if selected is None:
                rows[idx] = {
                    "timestamp": row["timestamp"],
                    "symbol": symbol,
                    "action": "HOLD",
                    "reason_code": "NO_RULE_MATCH",
                    "reason": "NO_RULE_MATCH",
                    "matched_rule_id": None,
                    "selected_gate_id": None,
                    "gate_results": gate_results,
                    "score_total": score,
                    "state": state,
                }
                continue

            rule_id = str(selected["id"])
            action = str(selected["action"])
            reason_code = reason_code_map[rule_id]
            if cooldown_bars > 0 and action != "HOLD":
                last_fire_by_symbol_action[(symbol, action)] = pos
            rows[idx] = {
                "timestamp": row["timestamp"],
                "symbol": symbol,
                "action": action,
                "reason_code": reason_code,
                "reason": reason_code,
                "matched_rule_id": rule_id,
                "selected_gate_id": selected_gate_id,
                "gate_results": gate_results,
                "score_total": score,
                "state": state,
            }

        output = pd.DataFrame([rows[idx] for idx in scoring_df.index], index=scoring_df.index)
        return SignalEngineResult(frame=output.reset_index(drop=True))

    def _collect_enabled_rules(self, *, signal_spec: dict[str, Any]) -> list[dict[str, Any]]:
        rules: list[dict[str, Any]] = []
        for field in ("entry_rules", "exit_rules", "hold_rules"):
            for item in signal_spec.get(field, []) or []:
                rule = dict(item)
                if not bool(rule.get("enabled", True)):
                    continue
                rules.append(rule)
        rules.sort(key=lambda item: int(item["priority_rank"]))
        return rules

    def _evaluate_entry_gates(
        self,
        *,
        gates: list[dict[str, Any]],
        condition_results: dict[str, Any],
    ) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for gate in gates:
            item = dict(gate)
            gate_id = str(item.get("id") or "")
            mode = str(item.get("mode") or "")
            side = str(item.get("side") or "")
            level = str(item.get("level") or "")
            conditions = [dict(c) for c in list(item.get("conditions") or [])]
            min_hit_raw = item.get("min_hit")
            min_hit = int(min_hit_raw) if isinstance(min_hit_raw, int) else None

            hit_count = 0
            required_count = 0
            hit_keys: list[str] = []
            miss_keys: list[str] = []
            for cond in conditions:
                key = str(cond.get("key") or "")
                is_required = bool(cond.get("required", False))
                if is_required:
                    required_count += 1
                hit = _to_bool(condition_results.get(key))
                if hit:
                    hit_count += 1
                    hit_keys.append(key)
                else:
                    miss_keys.append(key)

            passed = False
            if mode == "all_of":
                passed = hit_count == len(conditions)
            elif mode in {"n_of_m", "cross_tf"}:
                threshold = min_hit if min_hit is not None else len(conditions)
                passed = hit_count >= threshold

            output.append(
                {
                    "gate_id": gate_id,
                    "side": side,
                    "level": level,
                    "mode": mode,
                    "min_hit": min_hit,
                    "hit_count": hit_count,
                    "required_count": required_count,
                    "hit_keys": hit_keys,
                    "miss_keys": miss_keys,
                    "passed": passed,
                }
            )
        return output


__all__ = ["SignalEngine", "SignalEngineResult"]
