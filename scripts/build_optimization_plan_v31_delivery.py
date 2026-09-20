"""Build offline 3.1.0 optimization-plan delivery packages via Agent1.

Does not connect to MongoDB or call a model. Private source bytes stay on the caller
machine; this script writes JSON packages only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from rule_reader.application.rule_parsing.workflow_v31 import OptimizationPlanParsingService
from rule_reader.infrastructure.optimization_plan_artifacts import (
    write_optimization_plan_packages,
)
from rule_reader.infrastructure.optimization_plan_source import read_optimization_plan_source


async def _generate(source_root: Path, output_dir: Path) -> dict[str, object]:
    source = read_optimization_plan_source(source_root)
    service = OptimizationPlanParsingService()
    run = await service.generate_from_source_bytes(source.file_bytes, source.source_text)
    return write_optimization_plan_packages(output_dir, run)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        type=Path,
        required=True,
        help="Private RuleDataReferences checkout root.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory for the two complete delivery packages.",
    )
    args = parser.parse_args()
    summary = asyncio.run(_generate(args.source_root, args.output_dir))
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
