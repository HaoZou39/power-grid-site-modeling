import type { LocalPoint } from "./site_frame.js";
import { footprintCorners } from "./site_frame.js";

type FootprintSource = { id: string; x: number; y: number; theta: number; paretoLayer?: number };
type FootprintSize = { widthM: number; heightM: number };

/** Oriented building rectangle. Corners stay in local meters until the map projects them. */
export class BuildingFootprint {
  constructor(
    readonly id: string,
    readonly center: LocalPoint,
    readonly theta: number,
    readonly widthM: number,
    readonly heightM: number,
    readonly selected: boolean,
    /** 1-based recommendation rank; 0 when not recommended. */
    readonly rank: number = 0,
    readonly paretoLayer: number = 1,
  ) {}

  corners(): LocalPoint[] {
    return footprintCorners(this.center.x, this.center.y, this.theta, this.widthM, this.heightM);
  }

  toFeature(project: (point: LocalPoint) => number[]): {
    type: "Feature";
    properties: { id: string; selected: boolean; rank: number; pareto_layer: number };
    geometry: { type: "Polygon"; coordinates: number[][][] };
  } | null {
    if (!this.drawable()) return null;
    const ring = this.corners().map(project);
    ring.push(ring[0]);
    return {
      type: "Feature",
      properties: { id: this.id, selected: this.selected, rank: this.rank, pareto_layer: this.paretoLayer },
      geometry: { type: "Polygon", coordinates: [ring] },
    };
  }

  static layer(
    choices: readonly FootprintSource[],
    size: FootprintSize,
    selectedIndex: number,
    recommended: readonly string[] = [],
  ): BuildingFootprint[] {
    return choices.map((choice, index) => new BuildingFootprint(
      choice.id,
      { x: choice.x, y: choice.y },
      choice.theta,
      size.widthM,
      size.heightM,
      index === selectedIndex,
      recommended.indexOf(choice.id) + 1,
      choice.paretoLayer ?? 1,
    ));
  }

  private drawable(): boolean {
    const numbers = [this.center.x, this.center.y, this.theta, this.widthM, this.heightM];
    return numbers.every((value) => Number.isFinite(value)) && this.widthM > 0 && this.heightM > 0;
  }
}
