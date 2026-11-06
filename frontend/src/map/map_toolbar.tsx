import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { ReactNode, RefObject } from "react";
import { createPortal } from "react-dom";
import { SceneSelector } from "./scene_selector";
import { CLEAR_CLASS_TARGETS, LANDUSE_CLEAR_TITLE, LANDUSE_PAINT_TITLE, TOOLBAR_GROUPS, toolbarCommands } from "./toolbar_commands";
import type { LanduseEditClass, LanduseOperation, MapToolName, ToolbarCommand, ToolbarGroup } from "./toolbar_commands";
import { routingToolbarCommands } from "../routing/routing_toolbar";
import type { RoutingToolbar } from "../routing/routing_toolbar";

/** Word-style ribbon. Frequent map tools also stay in a dock beside the map. */
export function MapToolbar({
  tool,
  notify,
  focusSite,
  setTool,
  hasSelection,
  scenes,
  sceneId,
  onSceneChange,
  onRenameScene,
  onDeleteScene,
  sceneSwitchDisabled,
  sceneLabel,
  sceneDisabled,
  onPrepare,
  onNewScene,
  onImportData,
  importDataDisabled,
  optimizeLabel,
  optimizeDisabled,
  onOptimize,
  clearSolutionsDisabled,
  onClearSolutions,
  historyOpen,
  onImportCase,
  onSaveExperiment,
  saveExperimentDisabled,
  saveExperimentDisabledReason,
  onExportCsv,
  onExportJson,
  exportDisabled,
  onExportScenePng,
  sceneExportDisabled,
  landuseEditDisabled,
  originDisabled,
  originDisabledReason,
  onSoftwareUpdate,
  onAgentSettings,
  updateDisabled,
  themeLight,
  onToggleTheme,
  agentOpen,
  onToggleAgent,
  layersOpen,
  onToggleLayers,
  landuseOperation,
  landuseTargetClass,
  landuseEditing,
  onLanduseOperation,
  onLanduseClass,
  poseAddDisabled,
  poseAddDisabledReason,
  routing,
  canManageScenes = true,
}: {
  routing?: RoutingToolbar;
  canManageScenes?: boolean;
  poseAddDisabled?: boolean;
  poseAddDisabledReason?: string;
  tool: MapToolName;
  notify: (message: string) => void;
  focusSite: () => void;
  setTool: (tool: MapToolName) => void;
  hasSelection: boolean;
  scenes: readonly { id: string; title: string; ready: boolean }[];
  sceneId: string | null;
  onSceneChange: (sceneId: string) => void;
  onRenameScene: (sceneId: string, title: string) => Promise<void>;
  onDeleteScene: (sceneId: string) => void;
  sceneSwitchDisabled: boolean;
  sceneLabel: string;
  sceneDisabled: boolean;
  onPrepare: () => void;
  onNewScene: () => void;
  onImportData: () => void;
  importDataDisabled: boolean;
  optimizeLabel: string;
  optimizeDisabled: boolean;
  onOptimize: () => void;
  clearSolutionsDisabled: boolean;
  onClearSolutions: () => void;
  historyOpen: boolean;
  onImportCase: () => void;
  onSaveExperiment: () => void;
  saveExperimentDisabled: boolean;
  saveExperimentDisabledReason?: string;
  onExportCsv: () => void;
  onExportJson: () => void;
  exportDisabled: boolean;
  onExportScenePng: () => void;
  sceneExportDisabled: boolean;
  landuseEditDisabled: Partial<Record<LanduseEditClass, boolean>>;
  originDisabled: boolean;
  originDisabledReason?: string;
  onSoftwareUpdate: () => void;
  onAgentSettings: () => void;
  updateDisabled: boolean;
  themeLight: boolean;
  onToggleTheme: () => void;
  agentOpen: boolean;
  onToggleAgent: () => void;
  layersOpen: boolean;
  onToggleLayers: () => void;
  landuseOperation: LanduseOperation;
  landuseTargetClass: LanduseEditClass;
  landuseEditing: boolean;
  onLanduseOperation: (value: LanduseOperation) => void;
  onLanduseClass: (value: LanduseEditClass) => void;
}) {
  const [tab, setTab] = useState<ToolbarGroup>("主页");
  const baseCommands = toolbarCommands({
    tool,
    notify,
    focusSite,
    setTool,
    hasSelection,
    sceneLabel,
    sceneDisabled,
    onPrepare,
    onNewScene,
    onImportData,
    importDataDisabled,
    optimizeLabel,
    optimizeDisabled,
    onOptimize,
    clearSolutionsDisabled,
    onClearSolutions,
    historyOpen,
    onImportCase,
    onSaveExperiment,
    saveExperimentDisabled,
    saveExperimentDisabledReason,
    onExportCsv,
    onExportJson,
    exportDisabled,
    onExportScenePng,
    sceneExportDisabled,
    landuseEditDisabled,
    originDisabled,
    originDisabledReason,
    onSoftwareUpdate,
    onAgentSettings,
    updateDisabled,
    themeLight,
    onToggleTheme,
    poseAddDisabled,
    poseAddDisabledReason,
    canManageScenes,
  });
  const commands = routing ? routingToolbarCommands(baseCommands, routing) : baseCommands;
  return (
    <>
      <div className="map-toolbar">
        <div className="ribbon-tabs" role="tablist">
          <div className="ribbon-tab-group">
            {TOOLBAR_GROUPS.map((group) => (
              <button
                key={group}
                type="button"
                role="tab"
                aria-selected={tab === group}
                className={tab === group ? "active" : ""}
                onClick={() => setTab(group)}
              >
                {group}
              </button>
            ))}
          </div>
          <div className="ribbon-tab-trailing">
            <SceneSelector
              scenes={scenes}
              sceneId={sceneId}
              disabled={sceneSwitchDisabled}
              onChange={onSceneChange}
              onRename={onRenameScene}
              onDelete={onDeleteScene}
              onNewScene={onNewScene}
              canManage={canManageScenes}
            />
            <button
              type="button"
              className={agentOpen ? "agent-launch active" : "agent-launch"}
              aria-label="AI 助手"
              aria-pressed={agentOpen}
              title="AI 助手"
              onClick={onToggleAgent}
            >
              AI
            </button>
          </div>
        </div>
        <div className="ribbon-commands" role="tabpanel">
          {tab === "编辑"
            ? <EditRibbon commands={commands.filter((command) => command.group === "编辑")} routing={!!routing} landuseOperation={landuseOperation} landuseTargetClass={landuseTargetClass} landuseEditing={landuseEditing} onLanduseOperation={onLanduseOperation} onLanduseClass={onLanduseClass} />
            : commands.filter((command) => command.group === tab && command.id !== "new-scene").map((command) => (
              <ToolbarButton key={command.id} command={command} />
            ))}
          {tab === "视图" ? (
            <>
              <button
                type="button"
                className={layersOpen ? "layer-launch active" : "layer-launch"}
                aria-pressed={layersOpen}
                onClick={onToggleLayers}
              >
                图层
              </button>
            </>
          ) : null}
        </div>
      </div>
      <div className="map-quick">
        {commands.filter((command) => command.quick).map((command) => (
          <ToolbarButton key={command.id} command={command} />
        ))}
      </div>
    </>
  );
}

function EditRibbon({
  commands,
  routing,
  landuseOperation,
  landuseTargetClass,
  landuseEditing,
  onLanduseOperation,
  onLanduseClass,
}: {
  commands: ToolbarCommand[];
  routing: boolean;
  landuseOperation: LanduseOperation;
  landuseTargetClass: LanduseEditClass;
  landuseEditing: boolean;
  onLanduseOperation: (value: LanduseOperation) => void;
  onLanduseClass: (value: LanduseEditClass) => void;
}) {
  const byId = (id: string) => commands.find((command) => command.id === id);
  const loose = ["erase", "origin", "pose-add", "adjust"];
  const classDisabled = (id: LanduseEditClass) => byId(`landuse-${id}`)?.disabled ?? false;
  const clearDisabled = byId("landuse-clear-class")?.disabled ?? false;
  const pan = byId("pan");
  return (
    <>
      {pan && <ToolbarButton command={pan} />}
      {routing ? <>
        {["routing-start", "routing-end", "routing-adjust-endpoints"].map((id) => {
          const command = byId(id);
          return command ? <ToolbarButton key={id} command={command} /> : null;
        })}
        <ToolNest title="禁落塔区域" loop={byId("routing-no_tower")} box={byId("routing-no_tower-box")} />
        <ToolNest title="禁跨越区域" loop={byId("routing-no_cross")} box={byId("routing-no_cross-box")} />
      </> : <>
        <ToolNest title="禁区" loop={byId("exclusion")} box={byId("exclusion-box")} />
        <ToolNest title="可行域" loop={byId("feasible")} box={byId("feasible-box")} />
      </>}
      <LanduseTools
        landuseOperation={landuseOperation}
        landuseTargetClass={landuseTargetClass}
        landuseEditing={landuseEditing}
        paintBlocked={classDisabled(landuseTargetClass)}
        clearBlocked={clearDisabled}
        classBlocked={(id) => classDisabled(id) && (landuseOperation === "paint" || clearDisabled)}
        onLanduseOperation={onLanduseOperation}
        onLanduseClass={onLanduseClass}
      />
      {loose.map((id) => {
        const command = byId(id);
        return command ? <ToolbarButton key={id} command={command} /> : null;
      })}
    </>
  );
}

const LANDUSE_OPERATIONS: { id: LanduseOperation; short: string; label: string; title: string }[] = [
  { id: "paint", short: "设置", label: "设置类别", title: LANDUSE_PAINT_TITLE },
  { id: "clear", short: "清除", label: "清除指定类别", title: LANDUSE_CLEAR_TITLE },
];

function LanduseTools({
  landuseOperation,
  landuseTargetClass,
  landuseEditing,
  paintBlocked,
  clearBlocked,
  classBlocked,
  onLanduseOperation,
  onLanduseClass,
}: {
  landuseOperation: LanduseOperation;
  landuseTargetClass: LanduseEditClass;
  landuseEditing: boolean;
  paintBlocked: boolean;
  clearBlocked: boolean;
  classBlocked: (id: LanduseEditClass) => boolean;
  onLanduseOperation: (value: LanduseOperation) => void;
  onLanduseClass: (value: LanduseEditClass) => void;
}) {
  const [openMenu, setOpenMenu] = useState<"operation" | "class" | null>(null);
  const operationRef = useRef<HTMLButtonElement>(null);
  const classRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const operation = LANDUSE_OPERATIONS.find((item) => item.id === landuseOperation) ?? LANDUSE_OPERATIONS[0];
  const target = CLEAR_CLASS_TARGETS.find((item) => item.id === landuseTargetClass) ?? CLEAR_CLASS_TARGETS[0];
  const operationDisabled = (id: LanduseOperation) => id === "paint" ? paintBlocked : clearBlocked;
  useEffect(() => {
    if (!openMenu) return;
    const onPointer = (event: MouseEvent) => {
      const targetNode = event.target as Node;
      if (operationRef.current?.contains(targetNode) || classRef.current?.contains(targetNode) || menuRef.current?.contains(targetNode)) return;
      setOpenMenu(null);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpenMenu(null);
    };
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [openMenu]);
  const toggle = (which: "operation" | "class") => {
    if (openMenu === which) {
      setOpenMenu(null);
      return;
    }
    setOpenMenu(which);
    if (landuseEditing) return;
    if (which === "operation" && !operationDisabled(landuseOperation)) onLanduseOperation(landuseOperation);
    if (which === "class" && !classBlocked(landuseTargetClass)) onLanduseClass(landuseTargetClass);
  };
  return (
    <span className="tool-nest">
      <span>土地分类</span>
      <button
        ref={operationRef}
        type="button"
        className={landuseEditing ? "active" : ""}
        aria-pressed={landuseEditing}
        aria-haspopup="menu"
        aria-expanded={openMenu === "operation"}
        aria-label={`操作方式，${operation.label}`}
        title={operation.title}
        disabled={LANDUSE_OPERATIONS.every((item) => operationDisabled(item.id))}
        onClick={() => toggle("operation")}
      >
        {operation.short} ▾
      </button>
      <button
        ref={classRef}
        type="button"
        className={landuseEditing ? "active" : ""}
        aria-pressed={landuseEditing}
        aria-haspopup="menu"
        aria-expanded={openMenu === "class"}
        aria-label={`目标类别，${target.label}`}
        disabled={CLEAR_CLASS_TARGETS.every((item) => classBlocked(item.id))}
        onClick={() => toggle("class")}
      >
        {target.label} ▾
      </button>
      <RibbonMenu open={openMenu !== null} anchor={openMenu === "class" ? classRef : operationRef} menuRef={menuRef} label={openMenu === "class" ? "目标类别" : "操作方式"}>
        {openMenu === "operation" ? LANDUSE_OPERATIONS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="menuitemradio"
            aria-checked={item.id === landuseOperation}
            className={landuseEditing && item.id === landuseOperation ? "active" : ""}
            title={item.title}
            disabled={operationDisabled(item.id)}
            onClick={() => { setOpenMenu(null); onLanduseOperation(item.id); }}
          >
            {item.label}
          </button>
        )) : CLEAR_CLASS_TARGETS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="menuitemradio"
            aria-checked={item.id === landuseTargetClass}
            className={landuseEditing && item.id === landuseTargetClass ? "active" : ""}
            disabled={classBlocked(item.id)}
            onClick={() => { setOpenMenu(null); onLanduseClass(item.id); }}
          >
            {item.label}
          </button>
        ))}
      </RibbonMenu>
    </span>
  );
}

function RibbonMenu({
  open,
  anchor,
  menuRef,
  label,
  children,
}: {
  open: boolean;
  anchor: RefObject<HTMLButtonElement | null>;
  menuRef: RefObject<HTMLDivElement | null>;
  label: string;
  children: ReactNode;
}) {
  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const button = anchor.current;
      const menu = menuRef.current;
      if (!button || !menu) return;
      const rect = button.getBoundingClientRect();
      const left = Math.max(8, Math.min(rect.left, window.innerWidth - menu.offsetWidth - 8));
      menu.style.top = `${rect.bottom + 4}px`;
      menu.style.left = `${left}px`;
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open, anchor, menuRef, children]);
  const host = anchor.current?.closest(".map-app");
  if (!open || !host) return null;
  return createPortal(
    <div ref={menuRef} className="landuse-menu" role="menu" aria-label={label}>{children}</div>,
    host,
  );
}

function ToolNest({ title, loop, box }: { title: string; loop?: ToolbarCommand; box?: ToolbarCommand }) {
  const open = loop?.active || box?.active;
  return (
    <span className={open ? "tool-nest active" : "tool-nest"}>
      <span>{title}</span>
      {loop && <ToolbarButton command={loop} />}
      {box && <ToolbarButton command={box} />}
    </span>
  );
}

function ToolbarButton({ command }: { command: ToolbarCommand }) {
  const swatch = command.id.startsWith("show-") ? command.id.slice("show-".length) : "";
  return (
    <button
      type="button"
      className={[command.active ? "active" : "", command.emphasis === "primary" ? "toolbar-primary" : ""].filter(Boolean).join(" ")}
      disabled={command.disabled}
      title={command.title}
      onClick={command.run}
    >
      {swatch && <span className={`swatch ${swatch}`} />}
      {command.label}
    </button>
  );
}
