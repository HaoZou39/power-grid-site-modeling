from __future__ import annotations

import html
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

PARETO_3D_OBJECTIVES = ("dem_soft", "road_distance", "demand_distance")
PARETO_3D_HOVER_FIELDS = (
    "run_id",
    "x",
    "y",
    "theta",
    "scalar",
    "dem_soft",
    "road_distance",
    "demand_distance",
)


def _finite_float(record: Mapping[str, Any], field: str) -> float:
    if field not in record:
        raise ValueError(f"record is missing field {field!r}")
    value = float(record[field])
    if not np.isfinite(value):
        raise ValueError(f"field {field!r} contains NaN or Inf")
    return value


def _pareto_points(records: Sequence[Mapping[str, Any]]) -> list[dict[str, float | str]]:
    points: list[dict[str, float | str]] = []
    for record in records:
        point: dict[str, float | str] = {}
        for field in PARETO_3D_HOVER_FIELDS:
            value = _finite_float(record, field)
            point[field] = value
        points.append(point)
    return points


def write_pareto_3d_html(
    path: Path,
    pareto_records: Sequence[Mapping[str, Any]],
    title: str = "Pareto 3D Front",
) -> None:
    points = _pareto_points(pareto_records)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(points, ensure_ascii=True, separators=(",", ":"))
    escaped_title = html.escape(title, quote=True)
    path.write_text(_html_document(escaped_title, payload), encoding="utf-8")


def _html_document(title: str, points_json: str) -> str:
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
    <div class="muted">Axes: dem_soft, road_distance, demand_distance. Drag to rotate.</div>
  </header>
  <div class="wrap">
    <canvas id="plot" width="1100" height="760"></canvas>
    <aside>
      <div><span class="axis" style="background:#d7191c"></span>dem_soft</div>
      <div><span class="axis" style="background:#2c7bb6"></span>road_distance</div>
      <div><span class="axis" style="background:#1a9850"></span>demand_distance</div>
      <p id="count" class="muted"></p>
      <p class="muted">All objectives are interpreted as minimization objectives. Records are assumed to be precomputed Pareto records.</p>
    </aside>
  </div>
  <div id="tooltip"></div>
  <script>
    const points = {points_json};
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
    const rx = range("dem_soft"), ry = range("road_distance"), rz = range("demand_distance");
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
      drawAxis("dem_soft", 0.58, -0.5, -0.5, "#d7191c");
      drawAxis("road_distance", -0.5, 0.58, -0.5, "#2c7bb6");
      drawAxis("demand_distance", -0.5, -0.5, 0.58, "#1a9850");
      projected = points.map((p) => {{
        const q = project(norm(p.dem_soft, rx), norm(p.road_distance, ry), norm(p.demand_distance, rz));
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
      tooltip.innerHTML = `run_id: ${{p.run_id}}<br>x: ${{p.x.toFixed(3)}} y: ${{p.y.toFixed(3)}} theta: ${{p.theta.toFixed(3)}}<br>scalar: ${{p.scalar.toFixed(6)}}<br>dem_soft: ${{p.dem_soft.toFixed(6)}}<br>road_distance: ${{p.road_distance.toFixed(6)}}<br>demand_distance: ${{p.demand_distance.toFixed(6)}}`;
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
