"""Adapt captured candidate data to the standard case files without re-evaluation."""

from pathlib import Path

from experiments.case_artifacts import write_routing_case, write_site_case

SITE_METRICS = {
    "demSoft": "dem_soft", "roadDistance": "road_distance", "demandDistance": "demand_distance",
    "roadHaul": "road_haul_m", "offroadHaul": "offroad_haul_m", "haulRise": "haul_rise_m",
    "obstacleHardCount": "obstacle_hard_count",
}


def write_filter_artifacts(directory: Path, snapshot: dict, summary: dict) -> None:
    candidates = {item["id"]: item for item in snapshot["candidates"]}
    kept = [candidates[key] for key in snapshot["retained_ids"]]
    context = snapshot["context"]
    frame = context.get("frame")
    # Keep `frame` for filter reopen; also write coordinate_context so ordinary
    # site importers that only read data_metadata.json stay compatible.
    metadata = {"scene_id": snapshot["scene_name"], "data_version": snapshot["scene_version"], "frame": frame}
    if isinstance(frame, dict) and frame.get("crs") and frame.get("transform") and frame.get("width") and frame.get("height"):
        metadata["coordinate_context"] = {
            "scene_id": snapshot["scene_name"],
            "frame_id": snapshot["scene_version"].get("frame_id") or frame.get("frame_id"),
            "frame": frame,
        }
    if snapshot["problem_type"] == "routing":
        routes = [{**item["data"], "number": item["original_number"]} for item in kept]
        if "task" not in context or "frame" not in context or any(
            not {"id", "objectives", "is_feasible", "is_pareto", "violations", "points"} <= route.keys() for route in routes
        ):
            raise ValueError("筛选快照缺少完整线路或任务数据")
        summary.update(algorithm="routing_workspace", schema_version=1,
                       n_feasible=sum(route["is_feasible"] for route in routes), n_pareto=sum(route["is_pareto"] for route in routes),
                       objective_names=["tower_count", "length_3d_m", "bend_sum_rad", "crossing_3d_m"], clearance_status="净空未校核")
        write_routing_case(directory, routes, {**context["task"], "scene_name": snapshot["scene_name"], "experiment_name": summary["display_name"]},
                           context["frame"], metadata, summary)
        return
    if not {"widthM", "heightM", "form"} <= context.keys():
        raise ValueError("筛选快照缺少站址尺寸或约束数据")
    solutions = []
    for item in kept:
        pose = item["data"]
        if not {"x", "y", "theta", "rawMetrics"} <= pose.keys():
            raise ValueError("筛选快照缺少站址几何或完整精度指标")
        raw = pose.get("rawRecord") or {}
        pareto = raw.get("is_pareto")
        feasible = pose.get("feasible") == "可行"
        is_pareto = (pareto is True or str(pareto).lower() in {"true", "1"}) if pareto is not None else (
            feasible and not pose.get("manual") and pose.get("paretoLayer", 1) == 1)
        solutions.append({**raw, **{field: pose["rawMetrics"].get(key) for key, field in SITE_METRICS.items()},
            "run_id": item["id"], "id": item["id"], "x": pose["x"], "y": pose["y"], "theta": pose["theta"],
            "manual": bool(pose.get("manual")), "pareto_layer": pose.get("paretoLayer", 1),
            "derived_from": pose.get("derivedFrom", ""), "is_feasible": feasible, "is_pareto": is_pareto})
    form = {**context["form"], "scene_name": snapshot["scene_name"], "rect_w_m": context["widthM"], "rect_h_m": context["heightM"]}
    names = ["dem_soft", "offroad_haul_m", "haul_rise_m"]
    if form.get("origin_x") is not None: names.append("road_haul_m")
    if form.get("include_demand"): names.insert(1, "demand_distance")
    summary.update(algorithm="workspace_snapshot", n_runs=len(solutions), n_feasible=sum(row["is_feasible"] for row in solutions),
                   n_pareto=sum(row["is_pareto"] for row in solutions), objective_names=names)
    write_site_case(directory, form, solutions, metadata, summary)
