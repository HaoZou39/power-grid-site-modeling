"""Write a self-contained interactive Pareto 3D HTML figure."""

from __future__ import annotations

import html
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

# Single-objective searches store a scalar. The guided search leaves it blank.
PARETO_3D_OPTIONAL_FIELDS = ("scalar",)


def _finite_float(record: Mapping[str, Any], field: str) -> float:
    if field not in record:
        raise ValueError(f"record is missing field {field!r}")
    value = float(record[field])
    if not np.isfinite(value):
        raise ValueError(f"field {field!r} contains NaN or Inf")
    return value


def _optional_float(record: Mapping[str, Any], field: str) -> float | None:
    if field not in record:
        return None
    raw = record[field]
    if raw is None or raw == "":
        return None
    value = float(raw)
    if not np.isfinite(value):
        raise ValueError(f"field {field!r} contains NaN or Inf")
    return value


def _pareto_points(
    records: Sequence[Mapping[str, Any]],
    axes: tuple[str, str, str],
    extras: Sequence[str],
) -> list[dict[str, float | str]]:
    points: list[dict[str, float | str]] = []
    for record in records:
        point: dict[str, float | str] = {}
        for field in ("run_id", "x", "y", "theta"):
            point[field] = _finite_float(record, field)
        for field in axes:
            point[field] = _finite_float(record, field)
        for field in extras:
            value = _optional_float(record, field)
            if value is not None:
                point[field] = value
        for field in PARETO_3D_OPTIONAL_FIELDS:
            value = _optional_float(record, field)
            if value is not None:
                point[field] = value
        points.append(point)
    return points


def write_pareto_3d_html(
    path: Path,
    pareto_records: Sequence[Mapping[str, Any]],
    title: str = "Pareto 3D Front",
    *,
    axes: Sequence[str],
    hover_fields: Sequence[str] = (),
) -> None:
    chosen = tuple(axes)
    if len(chosen) != 3:
        raise ValueError("Pareto 3D figure needs exactly three axes")
    axis_names = (str(chosen[0]), str(chosen[1]), str(chosen[2]))
    points = _pareto_points(pareto_records, axis_names, hover_fields)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(points, ensure_ascii=True, separators=(",", ":"))
    path.write_text(
        _html_document(
            html.escape(title, quote=True),
            payload,
            json.dumps(list(axis_names), ensure_ascii=True, separators=(",", ":")),
            json.dumps(list(hover_fields), ensure_ascii=True, separators=(",", ":")),
            ", ".join(html.escape(name) for name in axis_names),
            _axis_legend(axis_names),
        ),
        encoding="utf-8",
    )


def _axis_legend(axes: tuple[str, str, str]) -> str:
    colors = ("#d7191c", "#2c7bb6", "#1a9850")
    return "\n".join(
        f'      <div><span class="axis" style="background:{color}"></span>{html.escape(name)}</div>'
        for name, color in zip(axes, colors)
    )


def _html_document(title: str, points_json: str, axes_json: str, extras_json: str, axis_text: str, legend: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    body {{ margin: 0; font-family: Arial, sans-serif; color: #202124; background: #ffffff; }}
    header {{ padding: 14px 18px 6px; }}
    h1 {{ margin: 0; font-size: 20px; font-weight: 600; }}
    .wrap {{ display: grid; grid-template-columns: minmax(0, 1fr) 260px; gap: 12px; padding: 0 18px 18px; }}
    canvas {{ width: 100%; height: 680px; border: 1px solid #d8dce3; background: #fbfbfc; cursor: grab; }}
    canvas:active {{ cursor: grabbing; }}
    aside {{ border: 1px solid #d8dce3; padding: 12px; font-size: 13px; line-height: 1.45; }}
    .muted {{ color: #5f6368; }}
    .axis {{ display: inline-block; width: 16px; height: 10px; margin-right: 6px; }}
    #tooltip {{ position: fixed; pointer-events: none; display: none; background: rgba(32,33,36,.94); color: white; padding: 8px 10px; border-radius: 4px; font-size: 12px; max-width: 260px; }}
    @media (max-width: 900px) {{ .wrap {{ grid-template-columns: 1fr; }} canvas {{ height: 520px; }} }}
  </style>
</head>
<body>
  <header>
    <h1>{title}</h1>
    <div class="muted">Axes: {axis_text}. Drag to rotate.</div>
  </header>
  <div class="wrap">
    <canvas id="plot" width="1100" height="760"></canvas>
    <aside>
{legend}
      <p id="count" class="muted"></p>
      <p class="muted">All objectives are interpreted as minimization objectives. Records are assumed to be precomputed Pareto records.</p>
    </aside>
  </div>
  <div id="tooltip"></div>
  <script>
    const points = {points_json};
    const axes = {axes_json};
    const extras = {extras_json};
    const canvas = document.getElementById("plot");
    const ctx = canvas.getContext("2d");
    const tooltip = document.getElementById("tooltip");
    document.getElementById("count").textContent = `${{points.length}} Pareto records`;
    let yaw = -0.72, pitch = 0.48, dragging = false, lastX = 0, lastY = 0;
    let projected = [];

    function range(key) {{
      if (points.length === 0) return [0, 1];
      let min = Infinity, max = -Infinity;
      for (const p of points) {{ min = Math.min(min, p[key]); max = Math.max(max, p[key]); }}
      if (min === max) return [min - 0.5, max + 0.5];
      return [min, max];
    }}
    const ranges = axes.map((key) => range(key));
    function norm(v, r) {{ return (v - r[0]) / (r[1] - r[0]) - 0.5; }}
    function rotate(x, y, z) {{
      const cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch);
      const x1 = cy * x + sy * z;
      const z1 = -sy * x + cy * z;
      const y1 = cp * y - sp * z1;
      const z2 = sp * y + cp * z1;
      return [x1, y1, z2];
    }}
    function project(x, y, z) {{
      const r = rotate(x, y, z);
      const scale = Math.min(canvas.width, canvas.height) * 0.58;
      return [canvas.width * 0.5 + r[0] * scale, canvas.height * 0.55 - r[1] * scale, r[2]];
    }}
    function drawAxis(label, x, y, z, color) {{
      const a = project(-0.5, -0.5, -0.5), b = project(x, y, z);
      ctx.strokeStyle = color; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
      ctx.fillStyle = color; ctx.fillText(label, b[0] + 6, b[1] - 6);
    }}
    function draw() {{
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.font = "15px Arial";
      drawAxis(axes[0], 0.58, -0.5, -0.5, "#d7191c");
      drawAxis(axes[1], -0.5, 0.58, -0.5, "#2c7bb6");
      drawAxis(axes[2], -0.5, -0.5, 0.58, "#1a9850");
      projected = points.map((p) => {{
        const q = project(norm(p[axes[0]], ranges[0]), norm(p[axes[1]], ranges[1]), norm(p[axes[2]], ranges[2]));
        return {{p, x: q[0], y: q[1], z: q[2]}};
      }}).sort((a, b) => a.z - b.z);
      for (const q of projected) {{
        ctx.beginPath();
        ctx.arc(q.x, q.y, 5.5, 0, Math.PI * 2);
        ctx.fillStyle = "#d7191c";
        ctx.fill();
        ctx.strokeStyle = "#ffffff";
        ctx.lineWidth = 1;
        ctx.stroke();
      }}
      if (points.length === 0) {{
        ctx.fillStyle = "#5f6368";
        ctx.fillText("No Pareto records", canvas.width * 0.5 - 55, canvas.height * 0.5);
      }}
    }}
    function nearest(mx, my) {{
      let best = null, bestD = 144;
      for (const q of projected) {{
        const d = (q.x - mx) ** 2 + (q.y - my) ** 2;
        if (d < bestD) {{ bestD = d; best = q; }}
      }}
      return best;
    }}
    canvas.addEventListener("mousedown", (e) => {{ dragging = true; lastX = e.clientX; lastY = e.clientY; }});
    window.addEventListener("mouseup", () => {{ dragging = false; }});
    window.addEventListener("mousemove", (e) => {{
      if (dragging) {{
        yaw += (e.clientX - lastX) * 0.01;
        pitch += (e.clientY - lastY) * 0.01;
        pitch = Math.max(-1.35, Math.min(1.35, pitch));
        lastX = e.clientX; lastY = e.clientY; draw();
      }}
      const rect = canvas.getBoundingClientRect();
      const mx = (e.clientX - rect.left) * canvas.width / rect.width;
      const my = (e.clientY - rect.top) * canvas.height / rect.height;
      const q = nearest(mx, my);
      if (!q) {{ tooltip.style.display = "none"; return; }}
      const p = q.p;
      const lines = [`run_id: ${{p.run_id}}`, `x: ${{p.x.toFixed(3)}} y: ${{p.y.toFixed(3)}} theta: ${{p.theta.toFixed(3)}}`];
      if (Number.isFinite(p.scalar)) lines.push(`scalar: ${{p.scalar.toFixed(6)}}`);
      for (const key of axes.concat(extras)) if (Number.isFinite(p[key])) lines.push(`${{key}}: ${{p[key].toFixed(6)}}`);
      tooltip.innerHTML = lines.join("<br>");
      tooltip.style.left = `${{e.clientX + 14}}px`;
      tooltip.style.top = `${{e.clientY + 14}}px`;
      tooltip.style.display = "block";
    }});
    canvas.addEventListener("mouseleave", () => {{ tooltip.style.display = "none"; }});
    draw();
  </script>
</body>
</html>
"""
