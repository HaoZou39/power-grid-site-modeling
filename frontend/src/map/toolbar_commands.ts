/** Toolbar commands. Add a new entry here when a later feature needs a button. */

export type LanduseClassId = "field" | "building" | "road" | "water";
export type MapToolName =
  | "pan"
  | "exclusion"
  | "exclusion-box"
  | "feasible"
  | "feasible-box"
  | "landuse-field"
  | "landuse-building"
  | "landuse-road"
  | "landuse-water"
  | "erase"
  | "pick"
  | "origin"
  | "adjust"
  | "pose-add"
  | "favorite-add"
  | "favorite-adjust";

export type LanduseEditClass = Extract<LanduseClassId, "field" | "building" | "road" | "water">;

export function landuseEditClass(tool: MapToolName): LanduseEditClass | null {
  if (tool === "landuse-field") return "field";
  if (tool === "landuse-building") return "building";
  if (tool === "landuse-road") return "road";
  if (tool === "landuse-water") return "water";
  return null;
}

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
export type ToolbarGroup = "文件" | "主页" | "视图" | "编辑" | "设置";

export const LANDUSE_CLASSES: { id: LanduseClassId; label: string }[] = [
  { id: "field", label: "农田" },
  { id: "building", label: "建筑" },
  { id: "road", label: "道路区域" },
  { id: "water", label: "水体" },
];

export const TOOLBAR_GROUPS: ToolbarGroup[] = ["文件", "主页", "视图", "编辑", "设置"];

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
  title?: string;
  run: () => void;
  emphasis?: "primary";
};

export function toolbarCommands(input: {
  tool: MapToolName;
  notify: (message: string) => void;
  focusSite: () => void;
  setTool: (tool: MapToolName) => void;
  hasSelection?: boolean;
  sceneLabel?: string;
  sceneDisabled?: boolean;
  onPrepare?: () => void;
  onNewScene?: () => void;
  onImportData?: () => void;
  importDataDisabled?: boolean;
  optimizeLabel?: string;
  optimizeDisabled?: boolean;
  onOptimize?: () => void;
  clearSolutionsDisabled?: boolean;
  onClearSolutions?: () => void;
  historyOpen?: boolean;
  onImportCase?: () => void;
  onExportCsv?: () => void;
  onExportJson?: () => void;
  exportDisabled?: boolean;
  onExportScenePng?: () => void;
  sceneExportDisabled?: boolean;
  landuseEditDisabled?: Partial<Record<LanduseEditClass, boolean>>;
  originDisabled?: boolean;
  originDisabledReason?: string;
  onSoftwareUpdate?: () => void;
  onAgentSettings?: () => void;
  updateDisabled?: boolean;
  themeLight?: boolean;
  onToggleTheme?: () => void;
  favoriteAdjustDisabled?: boolean;
  poseAddDisabled?: boolean;
  poseAddDisabledReason?: string;
}): ToolbarCommand[] {
  const command = (
    item: Omit<ToolbarCommand, "quick" | "disabled"> & { quick?: boolean; disabled?: boolean },
  ): ToolbarCommand => ({ quick: false, disabled: false, ...item });
  return [
    command({
      id: "new-scene",
      group: "文件",
      label: "新建场景…",
      active: false,
      run: () => input.onNewScene?.(),
    }),
    command({
      id: "import-data",
      group: "文件",
      label: "导入数据",
      active: false,
      disabled: input.importDataDisabled ?? false,
      run: () => (input.onImportData ? input.onImportData() : input.notify("导入数据尚未接入。")),
    }),
    command({
      id: "import-case",
      group: "文件",
      label: "导入案例",
      active: input.historyOpen ?? false,
      run: () => (input.onImportCase ? input.onImportCase() : input.notify("导入案例尚未接入。")),
    }),
    command({
      id: "export-solutions-csv",
      group: "文件",
      label: "导出全部方案 CSV",
      active: false,
      disabled: input.exportDisabled ?? false,
      run: () => (input.onExportCsv ? input.onExportCsv() : input.notify("导出方案尚未接入。")),
    }),
    command({
      id: "export-solutions-json",
      group: "文件",
      label: "导出全部方案 JSON",
      active: false,
      disabled: input.exportDisabled ?? false,
      run: () => (input.onExportJson ? input.onExportJson() : input.notify("导出方案尚未接入。")),
    }),
    command({
      id: "export-scene-png",
      group: "文件",
      label: "导出优化场景 PNG…",
      active: false,
      disabled: input.sceneExportDisabled ?? false,
      run: () => (input.onExportScenePng ? input.onExportScenePng() : input.notify("导出优化场景尚未接入。")),
    }),
    command({
      id: "prepare-scene",
      group: "主页",
      label: input.sceneLabel ?? "准备当前场景数据",
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
      emphasis: "primary",
      run: () => input.onOptimize?.(),
    }),
    command({
      id: "clear-solutions",
      group: "主页",
      label: "清空方案",
      active: false,
      disabled: input.clearSolutionsDisabled ?? false,
      run: () => input.onClearSolutions?.(),
    }),
    command({ id: "focus-site", group: "视图", label: "定位选址区", active: false, quick: true, run: input.focusSite }),
    command({ id: "pan", group: "编辑", label: "拖拽", active: input.tool === "pan", quick: true, run: () => input.setTool("pan") }),
    command({ id: "pose-add", group: "编辑", label: "添加方案", active: input.tool === "pose-add", disabled: input.poseAddDisabled ?? false, title: input.poseAddDisabledReason, run: () => input.setTool("pose-add") }),
    command({ id: "favorite-add", group: "编辑", label: "添加收藏点", active: input.tool === "favorite-add", run: () => input.setTool("favorite-add") }),
    command({
      id: "favorite-adjust",
      group: "编辑",
      label: "调整收藏点",
      active: input.tool === "favorite-adjust",
      disabled: input.favoriteAdjustDisabled ?? true,
      run: () => input.setTool("favorite-adjust"),
    }),
    command({ id: "exclusion", group: "编辑", label: "画圈", active: input.tool === "exclusion", run: () => input.setTool("exclusion") }),
    command({ id: "exclusion-box", group: "编辑", label: "方框", active: input.tool === "exclusion-box", run: () => input.setTool("exclusion-box") }),
    command({ id: "feasible", group: "编辑", label: "画圈", active: input.tool === "feasible", run: () => input.setTool("feasible") }),
    command({ id: "feasible-box", group: "编辑", label: "方框", active: input.tool === "feasible-box", run: () => input.setTool("feasible-box") }),
    command({ id: "erase", group: "编辑", label: "橡皮擦", active: input.tool === "erase", run: () => input.setTool("erase") }),
    command({
      id: "landuse-field",
      group: "编辑",
      label: "农田",
      active: input.tool === "landuse-field",
      disabled: input.landuseEditDisabled?.field ?? false,
      run: () => input.setTool("landuse-field"),
    }),
    command({
      id: "landuse-building",
      group: "编辑",
      label: "建筑",
      active: input.tool === "landuse-building",
      disabled: input.landuseEditDisabled?.building ?? false,
      run: () => input.setTool("landuse-building"),
    }),
    command({
      id: "landuse-road",
      group: "编辑",
      label: "道路",
      active: input.tool === "landuse-road",
      disabled: input.landuseEditDisabled?.road ?? false,
      run: () => input.setTool("landuse-road"),
    }),
    command({
      id: "landuse-water",
      group: "编辑",
      label: "水体",
      active: input.tool === "landuse-water",
      disabled: input.landuseEditDisabled?.water ?? false,
      run: () => input.setTool("landuse-water"),
    }),
    command({
      id: "origin",
      group: "编辑",
      label: "进货原点",
      active: input.tool === "origin",
      disabled: input.originDisabled ?? false,
      title: input.originDisabledReason,
      run: () => input.setTool("origin"),
    }),
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
    command({
      id: "theme-light",
      group: "设置",
      label: "浅色主题",
      active: input.themeLight ?? false,
      run: () => (input.onToggleTheme ? input.onToggleTheme() : input.notify("浅色主题尚未接入。")),
    }),
    command({
      id: "agent-settings",
      group: "设置",
      label: "AI 助手设置",
      active: false,
      run: () => (input.onAgentSettings ? input.onAgentSettings() : input.notify("AI 助手设置尚未接入。")),
    }),
    command({
      id: "software-update",
      group: "设置",
      label: "软件更新",
      active: false,
      disabled: input.updateDisabled ?? false,
      run: () => (input.onSoftwareUpdate ? input.onSoftwareUpdate() : input.notify("软件更新尚未接入。")),
    }),
  ];
}
