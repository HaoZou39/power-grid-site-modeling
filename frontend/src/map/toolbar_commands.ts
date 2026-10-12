/** Toolbar commands. Add a new entry here when a later feature needs a button. */

export type LanduseClassId = "field" | "building" | "road" | "water";
export type MapToolName = "pan" | "exclusion" | "exclusion-box" | "feasible" | "feasible-box" | "erase" | "pick" | "origin" | "adjust";

export function regionKind(tool: MapToolName): "exclusion" | "feasible" | null {
  if (tool === "exclusion" || tool === "exclusion-box") return "exclusion";
  if (tool === "feasible" || tool === "feasible-box") return "feasible";
  return null;
}

export function isLoopTool(tool: MapToolName): boolean {
  return tool === "exclusion" || tool === "feasible";
}

export function isBoxTool(tool: MapToolName): boolean {
  return tool === "exclusion-box" || tool === "feasible-box";
}
export type ToolbarGroup = "文件" | "主页" | "视图" | "编辑";

export const LANDUSE_CLASSES: { id: LanduseClassId; label: string }[] = [
  { id: "field", label: "农田" },
  { id: "building", label: "建筑" },
  { id: "road", label: "道路" },
  { id: "water", label: "水体" },
];

export const TOOLBAR_GROUPS: ToolbarGroup[] = ["文件", "主页", "视图", "编辑"];

export function hiddenLanduseClasses(): Record<LanduseClassId, boolean> {
  return { field: false, building: false, road: false, water: false };
}

export type ToolbarCommand = {
  id: string;
  group: ToolbarGroup;
  label: string;
  active: boolean;
  /** Also shown beside the map, so frequent tools stay available on every tab. */
  quick: boolean;
  disabled: boolean;
  run: () => void;
};

export function toolbarCommands(input: {
  tool: MapToolName;
  shownClasses: Record<LanduseClassId, boolean>;
  notify: (message: string) => void;
  focusSite: () => void;
  setTool: (tool: MapToolName) => void;
  toggleClass: (id: LanduseClassId) => void;
  hasSelection?: boolean;
  sceneLabel?: string;
  sceneDisabled?: boolean;
  onPrepare?: () => void;
  optimizeLabel?: string;
  optimizeDisabled?: boolean;
  onOptimize?: () => void;
  historyOpen?: boolean;
  onImportCase?: () => void;
}): ToolbarCommand[] {
  const command = (
    item: Omit<ToolbarCommand, "quick" | "disabled"> & { quick?: boolean; disabled?: boolean },
  ): ToolbarCommand => ({ quick: false, disabled: false, ...item });
  return [
    command({ id: "import-data", group: "文件", label: "导入数据", active: false, run: () => input.notify("导入数据尚未接入。") }),
    command({
      id: "import-case",
      group: "文件",
      label: "导入案例",
      active: input.historyOpen ?? false,
      run: () => (input.onImportCase ? input.onImportCase() : input.notify("导入案例尚未接入。")),
    }),
    command({
      id: "prepare-scene",
      group: "主页",
      label: input.sceneLabel ?? "构建场景数据",
      active: false,
      disabled: input.sceneDisabled ?? false,
      run: () => input.onPrepare?.(),
    }),
    command({
      id: "optimize",
      group: "主页",
      label: input.optimizeLabel ?? "开始优化",
      active: false,
      disabled: input.optimizeDisabled ?? false,
      run: () => input.onOptimize?.(),
    }),
    command({ id: "focus-site", group: "视图", label: "定位选址区", active: false, quick: true, run: input.focusSite }),
    ...LANDUSE_CLASSES.map((item) => command({
      id: `show-${item.id}`,
      group: "视图" as const,
      label: item.label,
      active: input.shownClasses[item.id],
      run: () => input.toggleClass(item.id),
    })),
    command({ id: "pan", group: "编辑", label: "拖拽", active: input.tool === "pan", quick: true, run: () => input.setTool("pan") }),
    command({ id: "exclusion", group: "编辑", label: "画圈", active: input.tool === "exclusion", run: () => input.setTool("exclusion") }),
    command({ id: "exclusion-box", group: "编辑", label: "方框", active: input.tool === "exclusion-box", run: () => input.setTool("exclusion-box") }),
    command({ id: "feasible", group: "编辑", label: "画圈", active: input.tool === "feasible", run: () => input.setTool("feasible") }),
    command({ id: "feasible-box", group: "编辑", label: "方框", active: input.tool === "feasible-box", run: () => input.setTool("feasible-box") }),
    command({ id: "erase", group: "编辑", label: "橡皮擦", active: input.tool === "erase", run: () => input.setTool("erase") }),
    command({ id: "pick", group: "编辑", label: "点选同类", active: input.tool === "pick", quick: true, run: () => input.setTool("pick") }),
    command({ id: "origin", group: "编辑", label: "进货原点", active: input.tool === "origin", run: () => input.setTool("origin") }),
    command({
      id: "adjust",
      group: "编辑",
      label: "调整方案",
      active: input.tool === "adjust",
      run: () => {
        if (!input.hasSelection) {
          input.notify("先点一个方案矩形。");
          return;
        }
        input.setTool("adjust");
      },
    }),
  ];
}
