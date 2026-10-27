"""Pre-registered migration gates and geometry diversity; never used by selection."""

import numpy as np


def shape_diversity(paths, chord_m, samples):
    if chord_m <= 0 or samples < 2:
        raise ValueError("diversity requires a positive chord and at least two samples")
    sampled = []
    for points in paths:
        points = np.asarray(points, dtype=float)
        lengths = np.r_[0., np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
        keep = np.r_[True, np.diff(lengths) > 0]
        if lengths[-1] <= 0:
            raise ValueError("diversity path must have positive length")
        positions = np.linspace(0, lengths[-1], samples)
        sampled.append(np.column_stack([np.interp(positions, lengths[keep], points[keep, axis]) for axis in [0, 1]]))
    distances = []
    for index, first in enumerate(sampled):
        for second in sampled[index + 1:]:
            distance = np.linalg.norm(first[:, None] - second[None, :], axis=2)
            distances.append((distance.min(0).mean() + distance.min(1).mean()) / (2 * chord_m))
    return float(np.mean(distances)) if distances else 0.


def migration_gate(baseline, candidate, *, quality_gain, special_gain,
                   regression, required_wins, seed_count, tolerance, special_metric=None):
    if set(baseline) != set(candidate):
        raise ValueError("migration gate requires identical task IDs")
    regressions, quality_cases, special_cases, details = [], [], [], {}
    for task_id, original in baseline.items():
        new = candidate[task_id]
        if set(original) != set(new) or len(original) != seed_count or seed_count < required_wins:
            raise ValueError("migration gate requires paired seeds")
        seeds = sorted(original)
        before, after = [original[s] for s in seeds], [new[s] for s in seeds]
        if sum(r["feasible"] for r in after) < sum(r["feasible"] for r in before):
            regressions.append(f"{task_id}:feasible_rate")
        item = {}
        for metric in ["igd_plus", "epsilon"]:
            left = np.array([r[metric] for r in before], dtype=float)
            right = np.array([r[metric] for r in after], dtype=float)
            if not np.isfinite(left).all() or not np.isfinite(right).all():
                regressions.append(f"{task_id}:{metric}_missing")
                continue
            a, b = float(np.median(left)), float(np.median(right))
            wins = int(np.count_nonzero(right < left - tolerance))
            item[metric] = {"baseline_median": a, "candidate_median": b, "paired_wins": wins}
            if b > a + max(abs(a) * regression, tolerance):
                regressions.append(f"{task_id}:{metric}")
            if metric == "igd_plus" and a > tolerance and b <= a * (1 - quality_gain) and wins >= required_wins:
                quality_cases.append(task_id)
        if special_metric:
            left = np.array([r[special_metric] for r in before], dtype=float)
            right = np.array([r[special_metric] for r in after], dtype=float)
            a, b = float(np.median(left)), float(np.median(right))
            wins = int(np.count_nonzero(right > left + tolerance))
            item[special_metric] = {"baseline_median": a, "candidate_median": b, "paired_wins": wins}
            if b > a + max(abs(a) * special_gain, tolerance) and wins >= required_wins:
                special_cases.append(task_id)
        details[task_id] = item
    return {"passed": not regressions and bool(quality_cases or special_cases),
            "regressions": regressions, "quality_cases": quality_cases, "special_cases": special_cases, "details": details}
