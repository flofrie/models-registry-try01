#!/usr/bin/env python
# SPDX-License-Identifier: MIT
"""Check two MODELS.json snapshots for suspicious differences."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from llm_registry.diff import (
    DEFAULT_COUNT_DROP_THRESHOLD,
    DEFAULT_COVERAGE_DROP_THRESHOLD,
    diff_models,
)
from llm_registry.output import read_models_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Warn if two MODELS.json snapshots differ suspiciously."
    )
    parser.add_argument("previous", type=Path, help="Path to the previous MODELS.json")
    parser.add_argument("current", type=Path, help="Path to the current MODELS.json")
    parser.add_argument(
        "--count-drop-threshold",
        type=float,
        default=DEFAULT_COUNT_DROP_THRESHOLD,
        help="Warn when provider available model count drops by more than this fraction.",
    )
    parser.add_argument(
        "--coverage-drop-threshold",
        type=float,
        default=DEFAULT_COVERAGE_DROP_THRESHOLD,
        help="Warn when field coverage drops by more than this fraction.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when warnings are found.",
    )
    args = parser.parse_args(argv)

    for path in (args.previous, args.current):
        if not path.exists():
            parser.error(f"{path} does not exist")

    previous = read_models_json(args.previous)
    current = read_models_json(args.current)
    warnings = diff_models(
        previous.values(),
        current.values(),
        count_drop_threshold=args.count_drop_threshold,
        coverage_drop_threshold=args.coverage_drop_threshold,
    )

    if warnings:
        print(f"Found {len(warnings)} model diff warning(s):")
        for warning in warnings:
            print(f"- [{warning.category}] {warning.message}")
        return 1 if args.strict else 0

    print("No model diff warnings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
