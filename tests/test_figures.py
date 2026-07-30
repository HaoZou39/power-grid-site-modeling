from __future__ import annotations

from pathlib import Path

import numpy as np

from figures import rectangle_corners, write_pareto_3d_html


def test_rectangle_corners_axis_aligned() -> None:
    corners = rectangle_corners(x=10.0, y=20.0, theta=0.0, width=4.0, height=2.0)
    expected = np.array(
        [
            [8.0, 19.0],
            [12.0, 19.0],
            [12.0, 21.0],
            [8.0, 21.0],
        ],
        dtype=np.float64,
    )
    np.testing.assert_allclose(corners, expected)


def test_write_pareto_3d_html_writes_self_contained_html() -> None:
    out = Path("outputs/test_figures/pareto_3d_interactive.html")
    records = [
        {
            "run_id": 1,
            "x": 10.0,
            "y": 20.0,
            "theta": 0.5,
            "scalar": 0.25,
            "dem_soft": 1.0,
            "road_distance": 2.0,
            "demand_distance": 3.0,
        }
    ]

    try:
        write_pareto_3d_html(out, records, "Test Pareto")

        text = out.read_text(encoding="utf-8")
        assert "Test Pareto" in text
        assert "dem_soft" in text
        assert "road_distance" in text
        assert "demand_distance" in text
        assert "run_id" in text
    finally:
        if out.exists():
            out.unlink()
        if out.parent.exists() and not any(out.parent.iterdir()):
            out.parent.rmdir()


def test_write_pareto_3d_html_rejects_missing_fields() -> None:
    try:
        write_pareto_3d_html(Path("outputs/test_figures/bad.html"), [{"run_id": 1}], "Bad")
    except ValueError as exc:
        assert "missing field" in str(exc)
    else:
        raise AssertionError("expected ValueError")
