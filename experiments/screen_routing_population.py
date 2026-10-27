"""Small population screen with explicit FE or generation stopping and cached priors."""

import argparse
from dataclasses import asdict, replace
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np
import torch

from algorithms.routing.pilot_reference.frozen_population import FrozenPopulation
from algorithms.routing.search import run_with_components
from config.project_config import RoutingConfig
from config.routing_task import RoutingRunConfig
from experiments.benchmark_routing import _save_candidates
from experiments.launch_routing_run import problem_from_snapshot
from experiments.routing_metrics import compare_front, reference_front
from experiments.routing_output import write_routing_json
from modeling.routing.types import Route


def load_seed_bank(row, count):
    path = Path(row["candidate_file"])
    with np.load(path) as saved:
        ids = np.flatnonzero((saved["evaluation_indices"] <= row["initialization_evaluations"])
            & (saved["counts"] >= row["tower_count_lower"]) & (saved["counts"] <= row["initial_tower_upper"]))
        ordered = sorted(ids,key=lambda i:(not bool(saved["feasible"][i]),int(saved["evaluation_indices"][i])))
        if len(ordered) < count:
            raise ValueError("cached initialization has fewer unique seeds than the common bank")
        chosen = ordered[:count]
        offsets = np.r_[0,saved["counts"].cumsum()]
        routes = [Route(saved["xy"][offsets[i]:offsets[i+1]]) for i in chosen]
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream,"sha256").hexdigest()
        metadata = {"source_candidate_sha256":digest,
                    "source_evaluation_indices":saved["evaluation_indices"][chosen].tolist(),
                    "historical_full_initialization_s":row["execution"]["timings"]["initialization_s"]}
    return routes,metadata


def screen(protocol, output):
    output.mkdir(parents=True,exist_ok=False)
    write_routing_json(output/"protocol.json",protocol)
    source = json.loads(Path(protocol["paired_report"]).read_text())["rows"]
    task = RoutingRunConfig.model_validate_json(Path(protocol["task_config"]).read_text())
    rows=[]
    for position,seed in enumerate(protocol["seeds"]):
        previous = next(r for r in source if r["task_id"]==protocol["task_id"] and r["arm"]=="gpu"
                        and r["seed"]==seed and r["paired_repeat"]==0)
        bank,provenance = load_seed_bank(previous,protocol["common_seed_count"])
        snapshot = Path(previous["candidate_file"]).parent/"snapshot"
        metadata = json.loads((snapshot/"data_metadata.json").read_text())
        started = time.perf_counter()
        problem = problem_from_snapshot(snapshot,task,metadata)
        context_s = time.perf_counter()-started
        original = RoutingConfig(**previous["config"])
        order = protocol["populations"] if position%2==0 else protocol["populations"][::-1]
        for population in order:
            caps=protocol["phase_limits"]
            core=replace(original.pilot.core,global_fraction=protocol["global_target"]/population,
                         local_fraction=original.pilot.core.local_fraction*protocol["common_seed_count"]/population)
            pilot=replace(original.pilot,core=core,local_budget_factor=math.ceil(caps["local_search"]/population),
                          global_budget_factor=math.ceil(caps["global_search"]/population))
            config=replace(original,popsize=population,max_evaluations=protocol["max_evaluations"],seed=seed,pilot=pilot,
                           devices=[protocol["device"]])
            sampler=FrozenPopulation(bank,previous["tower_count_lower"],previous["initial_tower_upper"],caps,
                seed+protocol["initial_seed_offset"],seed+protocol["global_seed_offset"])
            device=config.devices[0]
            torch.ones(1,device=device).sum().item()
            torch.cuda.synchronize(device);torch.cuda.empty_cache();torch.cuda.reset_peak_memory_stats(device)
            started=time.perf_counter()
            try:
                result=run_with_components(problem,config,sampler.components(max_generations=protocol.get("generations")))
                torch.cuda.synchronize(device)
                elapsed=time.perf_counter()-started
            finally:
                sampler.close()
                torch.cuda.empty_cache()
            if protocol.get("generations") is None:
                assert result.evaluation_count==protocol["max_evaluations"]
            else:
                assert result.generation_count==protocol["generations"]
                assert result.stop_reason=="generation_limit"
                assert result.evaluation_count<protocol["max_evaluations"]
            phases=result.execution["phase_evaluations"]
            assert sum(phases.values())==result.evaluation_count
            assert all(phases.get(name,0)<=limit for name,limit in caps.items())
            stats=result.execution["pilot_initialization"]
            assert stats["initial_unique_population"]==population
            assert stats["new_rrt_calls"]==stats["new_astar_calls"]==0
            result.execution.update(planner_device="cached_coordinates",initialization_evaluation_backend="tensor",
                                    global_seed_evaluation_backend="tensor")
            name=f"p{population}-seed{seed}"
            candidate=output/(name+".npz")
            _save_candidates(candidate,result)
            row={"population":population,"seed":seed,"elapsed_s":elapsed,"context_s":context_s,
                 "evaluation_count":result.evaluation_count,"generation_count":result.generation_count,
                 "stop_reason":result.stop_reason,
                 "n_candidates":len(result.routes),"n_feasible":sum(v.is_feasible for v in result.evaluations),
                 "n_pareto":len(result.pareto_indices),"candidate_file":str(candidate.resolve()),
                 "config":asdict(config),"execution":result.execution,"bank_provenance":provenance,
                 "input_hashes":previous["input_hashes"],"source_revision":protocol["source_revision"]}
            write_routing_json(output/(name+".json"),row)
            rows.append(row)
            write_routing_json(output/"completed.json",rows)
            print(json.dumps({k:row[k] for k in ["population","seed","elapsed_s","generation_count","n_feasible","n_pareto"]}),flush=True)
        pair=[row for row in rows if row["seed"]==seed]
        assert len({r["execution"]["pilot_initialization"]["initial_common_sha256"] for r in pair})==1
    fronts=[]
    for row in rows:
        with np.load(row["candidate_file"]) as saved:fronts.append(saved["objectives"][saved["pareto"]])
    reference=reference_front(fronts)
    if not len(reference):raise ValueError("screen found no feasible reference front")
    minimum=reference.min(0);scale=np.where(reference.max(0)>minimum,reference.max(0)-minimum,1.)
    np.save(output/"reference.npy",reference)
    for row,front in zip(rows,fronts):row["quality"]=compare_front(front,reference,minimum,scale)
    summary={str(population):{key:float(np.median([r["quality"][key] for r in rows if r["population"]==population]))
                             for key in ["igd_plus","epsilon"]} for population in protocol["populations"]}
    report={"protocol":protocol,"rows":rows,"quality_medians":summary,
            "normalization":{"minimum":minimum,"scale":scale,"kind":"best_known_union_not_global_optimum"},
            "timing_scope":"cached planning coordinates; includes device setup, random fill, search, archive and CPU feasible validation; excludes old planning and problem context"}
    write_routing_json(output/"report.json",report)
    print(json.dumps(summary,indent=2),flush=True)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    screen(json.loads(args.protocol.read_text()),args.output)


if __name__=="__main__":main()
