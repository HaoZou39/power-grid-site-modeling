import { useState } from "react";
import { TOOLBAR_GROUPS, toolbarCommands } from "./toolbar_commands";
import type { LanduseClassId, MapToolName, ToolbarCommand, ToolbarGroup } from "./toolbar_commands";

/** Word-style ribbon. Frequent map tools also stay in a dock beside the map. */
export function MapToolbar({
  tool,
  shownClasses,
  notify,
  focusSite,
  setTool,
  toggleClass,
  hasSelection,
  sceneLabel,
  sceneDisabled,
  onPrepare,
  optimizeLabel,
  optimizeDisabled,
  onOptimize,
  historyOpen,
  onImportCase,
}: {
  tool: MapToolName;
  shownClasses: Record<LanduseClassId, boolean>;
  notify: (message: string) => void;
  focusSite: () => void;
  setTool: (tool: MapToolName) => void;
  toggleClass: (id: LanduseClassId) => void;
  hasSelection: boolean;
  sceneLabel: string;
  sceneDisabled: boolean;
  onPrepare: () => void;
  optimizeLabel: string;
  optimizeDisabled: boolean;
  onOptimize: () => void;
  historyOpen: boolean;
  onImportCase: () => void;
}) {
  const [tab, setTab] = useState<ToolbarGroup>("主页");
  const commands = toolbarCommands({
    tool,
    shownClasses,
    notify,
    focusSite,
    setTool,
    toggleClass,
    hasSelection,
    sceneLabel,
    sceneDisabled,
    onPrepare,
    optimizeLabel,
    optimizeDisabled,
    onOptimize,
    historyOpen,
    onImportCase,
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
        </div>
        <div className="ribbon-commands" role="tabpanel">
          {tab === "编辑"
            ? <EditRibbon commands={commands.filter((command) => command.group === "编辑")} />
            : commands.filter((command) => command.group === tab).map((command) => (
              <ToolbarButton key={command.id} command={command} />
            ))}
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
  const loose = ["erase", "pick", "origin", "adjust"];
  const pan = byId("pan");
  return (
    <>
      {pan && <ToolbarButton command={pan} />}
      <ToolNest title="禁区" loop={byId("exclusion")} box={byId("exclusion-box")} />
      <ToolNest title="可行域" loop={byId("feasible")} box={byId("feasible-box")} />
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
