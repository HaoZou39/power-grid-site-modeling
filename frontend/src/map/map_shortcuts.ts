export type MapCommands = {
  drawing: boolean;
  pan: () => void;
  draw: () => void;
  focus: () => void;
  closeDraft: () => void;
  cancelDraft: () => void;
  undoPoint: () => void;
  previous: () => void;
  next: () => void;
  optimize: () => void;
};

const EDITABLE = new Set(["INPUT", "TEXTAREA", "SELECT"]);

/** Keyboard commands for the decision map. The handler list is the extension point. */
export class MapShortcuts {
  constructor(private readonly commands: () => MapCommands) {}

  handle(event: { key: string; target: unknown; preventDefault(): void }): void {
    const tagName = tagNameOf(event.target);
    if (EDITABLE.has(tagName)) return;
    const key = event.key.toLowerCase();
    const commands = this.commands();
    if (key === "v") commands.pan();
    if (key === "b") commands.draw();
    if (key === "f") commands.focus();
    if (event.key === "Enter" && commands.drawing) {
      event.preventDefault();
      commands.closeDraft();
    }
    if (key === "escape") commands.cancelDraft();
    if (event.key === "Backspace" && commands.drawing) {
      event.preventDefault();
      commands.undoPoint();
    }
    if (key === "[") commands.previous();
    if (key === "]") commands.next();
    if (key === "p") commands.optimize();
  }
}

function tagNameOf(target: unknown): string {
  if (typeof target !== "object" || target === null || !("tagName" in target)) return "";
  const tagName = target.tagName;
  return typeof tagName === "string" ? tagName : "";
}
