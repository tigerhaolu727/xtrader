from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from xtrader.strategy_profiles import (
    StrategyProfileContractError,
    StrategyProfileLoader,
    StrategyProfilePrecompileEngine,
    load_schema_file,
    schema_root_dir,
)


def _load_profile_payload() -> dict[str, object]:
    path = Path("configs/strategy-profiles/five_min_regime_momentum/v0.3.json")
    return json.loads(path.read_text(encoding="utf-8"))


def test_schema_assets_exist_and_are_valid_json() -> None:
    root = schema_root_dir()
    files = [
        "strategy_profile.v0.3.schema.json",
        "regime_spec.v0.3.schema.json",
        "signal_spec.v0.3.schema.json",
        "risk_spec.v0.3.schema.json",
    ]
    for filename in files:
        path = root / filename
        assert path.exists()
        payload = load_schema_file(filename)
        assert payload.get("type") == "object"


def test_profile_loader_accepts_v03_profile() -> None:
    loaded = StrategyProfileLoader().load("configs/strategy-profiles/five_min_regime_momentum/v0.3.json")
    assert loaded.resolved["schema_version"] == "xtrader.strategy_profile.v0.3"
    assert loaded.resolved["strategy_id"] == "five_min_regime_momentum"
    assert loaded.resolved["signal_spec"]["cooldown_scope"] == "symbol_action"


def test_profile_loader_rejects_missing_required_field() -> None:
    payload = _load_profile_payload()
    broken = copy.deepcopy(payload)
    broken.pop("regime_spec")
    with pytest.raises(StrategyProfileContractError) as exc:
        StrategyProfileLoader().load(broken)
    assert exc.value.code == "PC-CFG-003"
    assert exc.value.path == "$.regime_spec"


@pytest.mark.parametrize(
    ("mutator", "expected_path"),
    [
        (
            lambda item: item["signal_spec"].__setitem__("cooldown_scope", "by_symbol"),
            "$.signal_spec.cooldown_scope",
        ),
        (
            lambda item: item["risk_spec"]["size_model"]["params"].__setitem__("fraction", 1.2),
            "$.risk_spec.size_model.params.fraction",
        ),
    ],
)
def test_profile_loader_rejects_enum_and_range_errors(mutator, expected_path: str) -> None:
    payload = _load_profile_payload()
    broken = copy.deepcopy(payload)
    mutator(broken)
    with pytest.raises(StrategyProfileContractError) as exc:
        StrategyProfileLoader().load(broken)
    assert exc.value.code == "PC-CFG-003"
    assert exc.value.path == expected_path


def test_profile_precompile_fails_fast_on_schema_error() -> None:
    payload = _load_profile_payload()
    broken = copy.deepcopy(payload)
    broken.pop("signal_spec")
    result = StrategyProfilePrecompileEngine().compile(broken)
    assert result.status == "FAILED"
    assert result.error_code == "PC-CFG-003"
    assert "Field required" in str(result.error_message)
