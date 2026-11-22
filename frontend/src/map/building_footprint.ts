import type { LocalPoint } from "./site_frame.js";
import { footprintCorners } from "./site_frame.js";
import { siteCompareColor } from "./site_compare.js";

type FootprintSource = { id: string; x: number; y: number; theta: number; paretoLayer?: number; manual?: boolean };
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
    readonly manual: boolean = false,
    readonly comparisonColor: string | null = null,
  ) {}

  corners(): LocalPoint[] {
    return footprintCorners(this.center.x, this.center.y, this.theta, this.widthM, this.heightM);
  }

  toFeature(project: (point: LocalPoint) => number[]): {
    type: "Feature";
    properties: { id: string; selected: boolean; rank: number; pareto_layer: number; manual: boolean; compare_color?: string };
    geometry: { type: "Polygon"; coordinates: number[][][] };
  } | null {
    if (!this.drawable()) return null;
    const ring = this.corners().map(project);
    ring.push(ring[0]);
    return {
      type: "Feature",
      properties: { id: this.id, selected: this.selected, rank: this.rank, pareto_layer: this.paretoLayer, manual: this.manual,
        ...(this.comparisonColor ? { compare_color: this.comparisonColor } : {}) },
      geometry: { type: "Polygon", coordinates: [ring] },
    };
  }

  static layer(
    choices: readonly FootprintSource[],
    size: FootprintSize,
    selectedIndex: number,
    recommended: readonly string[] = [],
    retainedIds: ReadonlySet<string> | null = null,
    compared: readonly string[] = [],
  ): BuildingFootprint[] {
    return choices.flatMap((choice, index) => retainedIds && !retainedIds.has(choice.id) ? [] : [new BuildingFootprint(
      choice.id,
      { x: choice.x, y: choice.y },
      choice.theta,
      size.widthM,
      size.heightM,
      index === selectedIndex,
      recommended.indexOf(choice.id) + 1,
      choice.paretoLayer ?? 1,
      choice.manual ?? false,
      compared.includes(choice.id) ? siteCompareColor(compared.indexOf(choice.id)) : null,
    )]);
  }

  private drawable(): boolean {
    const numbers = [this.center.x, this.center.y, this.theta, this.widthM, this.heightM];
    return numbers.every((value) => Number.isFinite(value)) && this.widthM > 0 && this.heightM > 0;
  }
}
