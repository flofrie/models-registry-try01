"""Merge helpers for model registry updates."""

from typing import TypeVar

from pydantic import BaseModel

from llm_registry.schema.model_entry import ModelEntry

T = TypeVar("T", bound=BaseModel)


def merge_model_entries(existing: ModelEntry, new: ModelEntry) -> ModelEntry:
    """Merge a fresh entry into an existing registry entry.

    New non-null scalar values win. Null values in the fresh entry preserve
    existing data. Nested Pydantic models are merged field-by-field so partial
    API data cannot erase enriched pricing or capability subfields.
    """
    return _merge_model(existing, new)


def _merge_model(existing: T, new: T) -> T:
    merged = existing.model_copy(deep=True)
    for field_name in type(new).model_fields:
        new_value = getattr(new, field_name)
        if new_value is None:
            continue

        existing_value = getattr(existing, field_name, None)
        if isinstance(new_value, BaseModel):
            if not _has_present_value(new_value):
                continue
            if isinstance(existing_value, new_value.__class__):
                setattr(merged, field_name, _merge_model(existing_value, new_value))
            else:
                setattr(merged, field_name, new_value.model_copy(deep=True))
            continue

        setattr(merged, field_name, new_value)

    return merged


def _has_present_value(model: BaseModel) -> bool:
    for field_name in type(model).model_fields:
        value = getattr(model, field_name)
        if isinstance(value, BaseModel):
            if _has_present_value(value):
                return True
        elif value is not None:
            return True
    return False
