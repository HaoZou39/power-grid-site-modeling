import { useState } from "react";
import { TOOLBAR_GROUPS, toolbarCommands } from "./toolbar_commands";
import type { LanduseEditClass, MapToolName, ToolbarCommand, ToolbarGroup } from "./toolbar_commands";

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
  sceneSwitchDisabled,
  sceneLabel,
  sceneDisabled,
  onPrepare,
  onNewScene,
  optimizeLabel,
  optimizeDisabled,
  onOptimize,
  clearSolutionsDisabled,
  onClearSolutions,
  historyOpen,
  onImportCase,
  onExportCsv,
  onExportJson,
  exportDisabled,
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
  favoriteAdjustDisabled,
}: {
  tool: MapToolName;
  notify: (message: string) => void;
  focusSite: () => void;
  setTool: (tool: MapToolName) => void;
  hasSelection: boolean;
  scenes: readonly { id: string; title: string; ready: boolean }[];
  sceneId: string | null;
  onSceneChange: (sceneId: string) => void;
  sceneSwitchDisabled: boolean;
  sceneLabel: string;
  sceneDisabled: boolean;
  onPrepare: () => void;
  onNewScene: () => void;
  optimizeLabel: string;
  optimizeDisabled: boolean;
  onOptimize: () => void;
  clearSolutionsDisabled: boolean;
  onClearSolutions: () => void;
  historyOpen: boolean;
  onImportCase: () => void;
  onExportCsv: () => void;
  onExportJson: () => void;
  exportDisabled: boolean;
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
  favoriteAdjustDisabled: boolean;
}) {
  const [tab, setTab] = useState<ToolbarGroup>("主页");
  const commands = toolbarCommands({
    tool,
    notify,
    focusSite,
    setTool,
    hasSelection,
    sceneLabel,
    sceneDisabled,
    onPrepare,
    onNewScene,
    optimizeLabel,
    optimizeDisabled,
    onOptimize,
    clearSolutionsDisabled,
    onClearSolutions,
    historyOpen,
    onImportCase,
    onExportCsv,
    onExportJson,
    exportDisabled,
    landuseEditDisabled,
    originDisabled,
    originDisabledReason,
    onSoftwareUpdate,
    onAgentSettings,
    updateDisabled,
    themeLight,
    onToggleTheme,
    favoriteAdjustDisabled,
  });
  return (
    <>
      <div className="map-toolbar">
        <div className="ribbon-tabs" role="tablist">
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
          <span className="scene-switcher" aria-label="地区切换">
            {scenes.map((scene) => (
              <button
                key={scene.id}
                type="button"
                className={scene.id === sceneId ? "active" : ""}
                aria-pressed={scene.id === sceneId}
                disabled={sceneSwitchDisabled}
                title={scene.ready ? `${scene.title} · 已准备` : `${scene.title} · 尚未构建`}
                onClick={() => onSceneChange(scene.id)}
              >
                {scene.title}<i className={scene.ready ? "ready" : "pending"} />
              </button>
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
        <div className="ribbon-commands" role="tabpanel">
          {tab === "编辑"
            ? <EditRibbon commands={commands.filter((command) => command.group === "编辑")} />
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

function EditRibbon({ commands }: { commands: ToolbarCommand[] }) {
  const byId = (id: string) => commands.find((command) => command.id === id);
  const loose = ["erase", "origin", "adjust", "favorite-add", "favorite-adjust"];
  const landuse = ["landuse-field", "landuse-building", "landuse-road", "landuse-water"];
  const pan = byId("pan");
  return (
    <>
      {pan && <ToolbarButton command={pan} />}
      <ToolNest title="禁区" loop={byId("exclusion")} box={byId("exclusion-box")} />
      <ToolNest title="可行域" loop={byId("feasible")} box={byId("feasible-box")} />
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
