from __future__ import annotations

import argparse
import csv
from decimal import Decimal
from pathlib import Path


def parse_step(value: str) -> Decimal:
    step = Decimal(value)
    if not Decimal("0") < step <= Decimal("1"):
        raise argparse.ArgumentTypeError("step must be in (0, 1]")
    n = Decimal("1") / step
    if n != n.to_integral_value():
        raise argparse.ArgumentTypeError("step must evenly divide 1")
    return step


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an equally spaced three-objective preference CSV.")
    parser.add_argument("--step", type=parse_step, default=Decimal("0.1"))
    args = parser.parse_args()

    step: Decimal = args.step
    n = int(Decimal("1") / step)
    places = max(1, -step.normalize().as_tuple().exponent)
    step_label = format(step.normalize(), "f")
    output_path = Path(__file__).resolve().parent / f"preferences_step_{step_label}.csv"

    with output_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["preference_id", "weight_dem", "weight_road", "weight_demand"])
        preference_id = 0
        for i in range(n + 1):
            for j in range(n + 1 - i):
                k = n - i - j
                writer.writerow(
                    [
                        preference_id,
                        f"{Decimal(i) / n:.{places}f}",
                        f"{Decimal(j) / n:.{places}f}",
                        f"{Decimal(k) / n:.{places}f}",
                    ]
                )
                preference_id += 1

    print(f"Wrote {preference_id} preferences to {output_path}")


if __name__ == "__main__":
    main()
