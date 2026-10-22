"""Render completed initialization comparisons as static, browser-free figures."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def plot_comparison(directory: Path, seed: int = 123) -> None:
    summary = json.loads((directory / "summary.json").read_text())
    manifest = json.loads((directory / "manifest.json").read_text())
    arms = sorted(summary["arms"], key=lambda arm: (int(arm.rsplit("-", 1)[1]), arm))
    colors = ["#65758b", "#4696b5", "#d8902d", "#3b9c70"]
    fig, axes = plt.subplots(1, 3, figsize=(13, 4), layout="constrained")
    for ax, metric, title in zip(axes, ("hv", "igd_plus", "algorithm_seconds"),
                                 ("Hypervolume (higher is better)", "IGD+ (lower is better)", "Search time (seconds)")):
        values = [[run[metric] for run in summary["runs"] if run["arm"] == arm] for arm in arms]
        boxes = ax.boxplot(values, patch_artist=True)
        for box, color in zip(boxes["boxes"], colors):
            box.set_facecolor(color)
            box.set_alpha(0.55)
        for index, samples in enumerate(values, 1):
            ax.scatter(np.full(len(samples), index), samples, s=15, color="black", alpha=0.6)
        ax.set_xticks(np.arange(1, len(arms) + 1), arms, rotation=20)
        ax.set_title(title)
        ax.grid(axis="y", alpha=0.2)
    fig.savefig(directory / "metrics.png", dpi=180)
    plt.close(fig)
    scene = Path(manifest["scene_metadata"]["scene_dir"])
    dem = np.load(scene / "dem_1m.npy", mmap_mode="r")
    height, width = dem.shape
    fig, axes = plt.subplots(3, len(arms), figsize=(4 * len(arms), 11), layout="constrained")
    for column, arm in enumerate(arms):
        run = next(run for run in summary["runs"] if run["arm"] == arm and run["seed"] == seed)
        for row_index, stage in enumerate(("initial", "guided", "solutions")):
            ax = axes[row_index, column]
            with (Path(run["directory"]) / f"{stage}.csv").open() as stream:
                records = list(csv.DictReader(stream))
            xy = np.asarray([[float(row["x"]), float(row["y"])] for row in records])
            feasible = np.asarray([row["is_feasible"].lower() == "true" for row in records])
            ax.imshow(dem[::10, ::10], extent=(0, width, height, 0), cmap="Greys", alpha=0.45)
            ax.scatter(xy[~feasible, 0], xy[~feasible, 1], s=12, color="#bf4b45", label="infeasible")
            ax.scatter(xy[feasible, 0], xy[feasible, 1], s=14, color=colors[column], label="feasible")
            ax.set_xlim(0, width)
            ax.set_ylim(height, 0)
            ax.set_aspect("equal")
            ax.set_title(f"{arm} / {stage}")
            ax.set_xlabel("x (m)")
            ax.set_ylabel("y (m)")
    steps = manifest["base_config"]["guided_search"]["guide_steps"]
    fig.suptitle(f"Initialization, after {steps} guidance steps, and final population / seed {seed}\n"
                 "Red: infeasible; arm color: feasible")
    fig.savefig(directory / f"positions_seed{seed}.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--seed", type=int, default=123)
    args = parser.parse_args()
    plot_comparison(args.directory, args.seed)
