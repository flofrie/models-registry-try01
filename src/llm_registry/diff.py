# SPDX-License-Identifier: MIT
"""Quality checks for comparing two MODELS.json snapshots."""

from dataclasses import dataclass, field
from typing import Iterable

from llm_registry.schema.model_entry import ModelEntry


DEFAULT_COUNT_DROP_THRESHOLD = 0.25
DEFAULT_COVERAGE_DROP_THRESHOLD = 0.10

FIELD_PATHS = (
    "context_window",
    "max_output_tokens",
    "pricing.input_per_1m",
    "pricing.output_per_1m",
)


@dataclass(frozen=True)
class DiffWarning:
    """Structured warning emitted by `diff_models`."""

    category: str
    provider: str
    message: str
    details: dict[str, object] = field(default_factory=dict)


def diff_models(
    previous: Iterable[ModelEntry],
    current: Iterable[ModelEntry],
    *,
    count_drop_threshold: float = DEFAULT_COUNT_DROP_THRESHOLD,
    coverage_drop_threshold: float = DEFAULT_COVERAGE_DROP_THRESHOLD,
) -> list[DiffWarning]:
    """Compare two model snapshots and return suspicious changes.

    This compares two concrete output snapshots. If a normal update preserved
    stale non-null enrichment during merge, that fresh extraction failure may
    not appear in the final output and therefore cannot be detected here.
    """
    previous_by_key = _by_key(previous)
    current_by_key = _by_key(current)

    warnings: list[DiffWarning] = []
    warnings.extend(
        _count_drop_warnings(
            previous_by_key,
            current_by_key,
            count_drop_threshold=count_drop_threshold,
        )
    )
    warnings.extend(_missing_model_warnings(previous_by_key, current_by_key))
    warnings.extend(
        _coverage_drop_warnings(
            previous_by_key,
            current_by_key,
            coverage_drop_threshold=coverage_drop_threshold,
        )
    )
    return warnings


def _by_key(models: Iterable[ModelEntry]) -> dict[tuple[str, str], ModelEntry]:
    return {(model.provider, model.model_id): model for model in models}


def _providers(*snapshots: dict[tuple[str, str], ModelEntry]) -> set[str]:
    return {provider for snapshot in snapshots for provider, _ in snapshot}


def _count_drop_warnings(
    previous: dict[tuple[str, str], ModelEntry],
    current: dict[tuple[str, str], ModelEntry],
    *,
    count_drop_threshold: float,
) -> list[DiffWarning]:
    warnings = []
    for provider in sorted(_providers(previous, current)):
        previous_count = _available_count(previous, provider)
        current_count = _available_count(current, provider)
        if previous_count == 0 or current_count >= previous_count:
            continue

        drop_fraction = (previous_count - current_count) / previous_count
        if drop_fraction > count_drop_threshold:
            warnings.append(
                DiffWarning(
                    category="provider_count_drop",
                    provider=provider,
                    message=(
                        f"{provider}: available model count dropped from "
                        f"{previous_count} to {current_count} ({drop_fraction:.1%})"
                    ),
                    details={
                        "previous_count": previous_count,
                        "current_count": current_count,
                        "drop_fraction": drop_fraction,
                        "threshold": count_drop_threshold,
                    },
                )
            )
    return warnings


def _available_count(snapshot: dict[tuple[str, str], ModelEntry], provider: str) -> int:
    return sum(1 for (p, _), model in snapshot.items() if p == provider and model.available)


def _missing_model_warnings(
    previous: dict[tuple[str, str], ModelEntry],
    current: dict[tuple[str, str], ModelEntry],
) -> list[DiffWarning]:
    warnings = []
    for key, previous_model in sorted(previous.items()):
        provider, model_id = key
        if not previous_model.available:
            continue

        current_model = current.get(key)
        if current_model is not None and current_model.available:
            continue

        reason = "missing from current file" if current_model is None else "marked unavailable"
        warnings.append(
            DiffWarning(
                category="missing_model",
                provider=provider,
                message=(
                    f"{provider}/{model_id}: {reason}; may be provider delisting "
                    "or discovery regression"
                ),
                details={"model_id": model_id, "reason": reason},
            )
        )
    return warnings


def _coverage_drop_warnings(
    previous: dict[tuple[str, str], ModelEntry],
    current: dict[tuple[str, str], ModelEntry],
    *,
    coverage_drop_threshold: float,
) -> list[DiffWarning]:
    warnings = []
    for provider in sorted(_providers(previous, current)):
        common_available = [
            key
            for key, previous_model in previous.items()
            if key[0] == provider
            and previous_model.available
            and key in current
            and current[key].available
        ]
        if not common_available:
            continue

        for field_path in FIELD_PATHS:
            previous_with_field = [
                key for key in common_available if _field_value(previous[key], field_path) is not None
            ]
            if not previous_with_field:
                continue

            current_with_field = [
                key for key in previous_with_field if _field_value(current[key], field_path) is not None
            ]
            drop_fraction = (
                len(previous_with_field) - len(current_with_field)
            ) / len(previous_with_field)

            if drop_fraction > coverage_drop_threshold:
                warnings.append(
                    DiffWarning(
                        category="field_coverage_drop",
                        provider=provider,
                        message=(
                            f"{provider}: {field_path} coverage dropped from "
                            f"{len(previous_with_field)} to {len(current_with_field)} "
                            f"models ({drop_fraction:.1%})"
                        ),
                        details={
                            "field": field_path,
                            "previous_count": len(previous_with_field),
                            "current_count": len(current_with_field),
                            "drop_fraction": drop_fraction,
                            "threshold": coverage_drop_threshold,
                        },
                    )
                )
    return warnings


def _field_value(model: ModelEntry, field_path: str) -> object:
    value: object = model
    for part in field_path.split("."):
        value = getattr(value, part, None)
        if value is None:
            return None
    return value
