"""Fixed matrix-native strategy for controlled factor-rank research."""
from __future__ import annotations

import numpy as np

from app.backtest.matrix import (
    MarketDataMatrix,
    SignalMatrix,
    build_matrix_score,
    make_signal_matrix,
)

META = {
    "id": "factor_rank_research",
    "name": "因子排名研究",
    "description": "受控多因子截面评分、阈值与排名选股策略",
    "tags": ["因子", "研究", "截面排名"],
    "asset_types": ["stock", "etf"],
    "timeframes": ["1d"],
    "research_only": True,
    "params": [
        {
            "id": "entry_score",
            "label": "入场最低分",
            "type": "float",
            "default": 70.0,
            "min": 0.0,
            "max": 100.0,
            "step": 5.0,
        },
        {
            "id": "exit_score",
            "label": "离场最高分",
            "type": "float",
            "default": 40.0,
            "min": 0.0,
            "max": 100.0,
            "step": 5.0,
        },
        {
            "id": "top_rank",
            "label": "每日最多入选",
            "type": "int",
            "default": 20,
            "min": 1,
            "max": 100,
            "step": 1,
        },
    ],
    # Research-generated scoring is supplied in params. Keeping META scoring
    # empty prevents the framework pipeline from replacing the strategy score.
    "scoring": {},
    "order_by": "score",
    "descending": True,
    "limit": 100,
}

EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = ["signal_factor_rank_entry"]
EXIT_SIGNALS = ["signal_factor_rank_exit"]
STOP_LOSS = -0.08
MAX_HOLD_DAYS = 30

_MAX_FACTORS = 4
_VALID_DIRECTIONS = {"high", "low"}


def normalize_scoring_and_directions(
    scoring: object,
    directions: object = None,
) -> tuple[dict[str, float], dict[str, str]]:
    """Normalize research scoring shorthands.

    Negative weights and "-factor" names both mean lower factor values rank better.
    The returned scoring always uses canonical factor names and positive weights.
    """
    normalized_scoring, implicit_directions = _validated_scoring_config(scoring)
    return normalized_scoring, _merged_directions(
        implicit_directions,
        directions,
        normalized_scoring,
    )


class FactorRankResearchMatrixStrategy:
    def __init__(
        self,
        scoring: dict[str, float] | None = None,
        directions: dict[str, str] | None = None,
    ) -> None:
        scoring_config = _validated_scoring_config(scoring) if scoring is not None else None
        self._scoring = scoring_config[0] if scoring_config is not None else None
        self._directions = (
            _merged_directions(scoring_config[1], directions, self._scoring)
            if scoring_config is not None and self._scoring is not None
            else None
        )

    def required_fields(self) -> frozenset[str]:
        return frozenset({
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "turnover_rate",
        })

    def required_warmup_bars(self, params: dict) -> int:
        del params
        return 60

    def required_fields_for_params(self, params: dict) -> frozenset[str]:
        if self._scoring is not None:
            return frozenset(self._scoring)
        raw = params.get("scoring")
        if raw is None:
            return frozenset()
        return frozenset(_validated_scoring(raw))

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        if self._scoring is not None:
            scoring = self._scoring
            directions = self._directions or {}
        else:
            scoring, directions = normalize_scoring_and_directions(
                params.get("scoring"),
                params.get("directions"),
            )
        entry_score = _bounded_float(params.get("entry_score", 70.0), "entry_score")
        exit_score = _bounded_float(params.get("exit_score", 40.0), "exit_score")
        top_rank = int(params.get("top_rank", 20))
        if not 1 <= top_rank <= 100:
            raise ValueError("top_rank must be between 1 and 100")
        if exit_score > entry_score:
            raise ValueError("exit_score must not exceed entry_score")

        universe = np.isfinite(market.close)
        score = build_matrix_score(
            market,
            universe,
            scoring,
            "score",
            True,
            fallback=np.zeros(market.shape, dtype=np.float32),
            directions=directions,
        )
        entry = universe & (score >= np.float32(entry_score))
        entry = _limit_top_rank(entry, score, top_rank)
        exit_ = universe & (score <= np.float32(exit_score))
        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            exit=exit_.astype(np.uint8),
            score=score,
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            exit_signal_code=np.where(exit_, 0, -1).astype(np.int16),
            entry_signal_ids=("signal_factor_rank_entry",),
            exit_signal_ids=("signal_factor_rank_exit",),
        )


def _validated_scoring(raw: object) -> dict[str, float]:
    return _validated_scoring_config(raw)[0]


def _validated_scoring_config(raw: object) -> tuple[dict[str, float], dict[str, str]]:
    if not isinstance(raw, dict) or not raw:
        raise ValueError("factor-rank research requires a non-empty scoring mapping")
    if len(raw) > _MAX_FACTORS:
        raise ValueError(f"factor-rank research supports at most {_MAX_FACTORS} factors")
    scoring: dict[str, float] = {}
    directions: dict[str, str] = {}
    for name, value in raw.items():
        if not isinstance(name, str) or not name:
            raise ValueError("scoring factor names must be non-empty strings")
        factor_name = name[1:] if name.startswith("-") else name
        if not factor_name:
            raise ValueError("scoring factor names must be non-empty strings")
        if factor_name in scoring:
            raise ValueError(f"scoring contains duplicate factor {factor_name!r}")
        if isinstance(value, bool):
            raise ValueError(f"scoring weight for {name!r} must be numeric")
        try:
            weight = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"scoring weight for {name!r} must be numeric") from exc
        if not np.isfinite(weight) or weight == 0.0:
            raise ValueError(f"scoring weight for {name!r} must be finite and non-zero")
        scoring[factor_name] = abs(weight)
        if name.startswith("-") or weight < 0.0:
            directions[factor_name] = "low"
    return scoring, directions


def _merged_directions(
    implicit: dict[str, str],
    raw: object,
    scoring: dict[str, float],
) -> dict[str, str]:
    directions = _validated_directions(raw, scoring)
    directions.update(implicit)
    return directions


def _validated_directions(
    raw: object,
    scoring: dict[str, float],
) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("directions must be a mapping")
    unknown = sorted(set(raw) - set(scoring))
    if unknown:
        raise ValueError(f"directions contain factors absent from scoring: {unknown}")
    directions: dict[str, str] = {}
    for name, value in raw.items():
        if value not in _VALID_DIRECTIONS:
            raise ValueError(
                f"direction for {name!r} must be one of {sorted(_VALID_DIRECTIONS)}"
            )
        directions[str(name)] = str(value)
    return directions


def _bounded_float(value: object, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not np.isfinite(number) or not 0.0 <= number <= 100.0:
        raise ValueError(f"{name} must be between 0 and 100")
    return number


def _limit_top_rank(
    eligible: np.ndarray,
    score: np.ndarray,
    top_rank: int,
) -> np.ndarray:
    result = np.zeros(eligible.shape, dtype=bool)
    for time_id in range(eligible.shape[0]):
        asset_ids = np.flatnonzero(eligible[time_id])
        if asset_ids.size <= top_rank:
            result[time_id, asset_ids] = True
            continue
        # mergesort preserves asset-axis order for equal scores.
        order = np.argsort(-score[time_id, asset_ids], kind="stable")[:top_rank]
        result[time_id, asset_ids[order]] = True
    return result


MATRIX_STRATEGY = FactorRankResearchMatrixStrategy()
