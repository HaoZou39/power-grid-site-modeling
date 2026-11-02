import { useState } from "react";
import { TOOLBAR_GROUPS, toolbarCommands } from "./toolbar_commands";
import type { LanduseEditClass, MapToolName, ToolbarCommand, ToolbarGroup } from "./toolbar_commands";
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
  poseAddDisabled,
  poseAddDisabledReason,
  routing,
}: {
  routing?: RoutingToolbar;
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
}) {
  const [tab, setTab] = useState<ToolbarGroup>("主页");
  const [deletingId, setDeletingId] = useState<string | null>(null);
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
            <span className="scene-switcher" aria-label="地区切换">
              {scenes.map((scene) => (
                deletingId === scene.id ? (
                  <span key={scene.id} className="scene-delete-confirm" role="group" aria-label={`确认删除 ${scene.title}`}>
                    <em>删除「{scene.title}」？</em>
                    <button type="button" onClick={() => { setDeletingId(null); onDeleteScene(scene.id); }}>删除</button>
                    <button type="button" onClick={() => setDeletingId(null)}>取消</button>
                  </span>
                ) : (
                  <span key={scene.id} className="scene-item">
                    <button
                      type="button"
                      className={scene.id === sceneId ? "active" : ""}
                      aria-pressed={scene.id === sceneId}
                      disabled={sceneSwitchDisabled}
                      title={scene.ready ? `${scene.title} · 已准备` : `${scene.title} · 尚未构建`}
                      onClick={() => onSceneChange(scene.id)}
                    >
                      {scene.title}<i className={scene.ready ? "ready" : "pending"} />
                    </button>
                    <button
                      type="button"
                      className="scene-delete"
                      aria-label={`删除场景 ${scene.title}`}
                      title={scene.id === sceneId ? "当前打开的场景不能删除" : `删除场景 ${scene.title}`}
                      disabled={sceneSwitchDisabled || scene.id === sceneId}
                      onClick={() => setDeletingId(scene.id)}
                    >
                      ×
                    </button>
                  </span>
                )
              ))}
            </span>
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
            ? <EditRibbon commands={commands.filter((command) => command.group === "编辑")} routing={!!routing} />
            : commands.filter((command) => command.group === tab).map((command) => (
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

function EditRibbon({ commands, routing }: { commands: ToolbarCommand[]; routing: boolean }) {
  const byId = (id: string) => commands.find((command) => command.id === id);
  const loose = ["erase", "origin", "pose-add", "adjust"];
  const landuse = ["landuse-field", "landuse-building", "landuse-road", "landuse-water", "landuse-clear-water"];
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
      <span className={landuse.some((id) => byId(id)?.active) ? "tool-nest active" : "tool-nest"}>
        <span>土地类型</span>
        {landuse.map((id) => {
          const command = byId(id);
          return command ? <ToolbarButton key={id} command={command} /> : null;
        })}
      </span>
      {loose.map((id) => {
        const command = byId(id);
        return command ? <ToolbarButton key={id} command={command} /> : null;
      })}
    </>
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
