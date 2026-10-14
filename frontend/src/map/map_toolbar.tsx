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
  sceneLabel,
  sceneDisabled,
  onPrepare,
  optimizeLabel,
  optimizeDisabled,
  onOptimize,
  historyOpen,
  onImportCase,
  onExportCsv,
  onExportJson,
  exportDisabled,
  landuseEditDisabled,
  onSoftwareUpdate,
  onAgentSettings,
  updateDisabled,
  agentOpen,
  onToggleAgent,
  layersOpen,
  onToggleLayers,
}: {
  tool: MapToolName;
  notify: (message: string) => void;
  focusSite: () => void;
  setTool: (tool: MapToolName) => void;
  hasSelection: boolean;
  sceneLabel: string;
  sceneDisabled: boolean;
  onPrepare: () => void;
  optimizeLabel: string;
  optimizeDisabled: boolean;
  onOptimize: () => void;
  historyOpen: boolean;
  onImportCase: () => void;
  onExportCsv: () => void;
  onExportJson: () => void;
  exportDisabled: boolean;
  landuseEditDisabled: Partial<Record<LanduseEditClass, boolean>>;
  onSoftwareUpdate: () => void;
  onAgentSettings: () => void;
  updateDisabled: boolean;
  agentOpen: boolean;
  onToggleAgent: () => void;
  layersOpen: boolean;
  onToggleLayers: () => void;
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
    optimizeLabel,
    optimizeDisabled,
    onOptimize,
    historyOpen,
    onImportCase,
    onExportCsv,
    onExportJson,
    exportDisabled,
    landuseEditDisabled,
    onSoftwareUpdate,
    onAgentSettings,
    updateDisabled,
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
            <button
              type="button"
              className={layersOpen ? "layer-launch active" : "layer-launch"}
              aria-pressed={layersOpen}
              onClick={onToggleLayers}
            >
              图层
            </button>
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
  const loose = ["erase", "origin", "adjust"];
  const landuse = ["landuse-field", "landuse-building", "landuse-water"];
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
    <button type="button" className={command.active ? "active" : ""} disabled={command.disabled} onClick={command.run}>
      {swatch && <span className={`swatch ${swatch}`} />}
      {command.label}
    </button>
  );
}
