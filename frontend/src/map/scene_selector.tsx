import { useEffect, useRef, useState } from "react";

type SceneChoice = { id: string; title: string; ready: boolean };

export function SceneSelector({
  scenes,
  sceneId,
  disabled,
  onChange,
  onRename,
  onDelete,
  onNewScene,
  canManage = true,
}: {
  scenes: readonly SceneChoice[];
  sceneId: string | null;
  disabled: boolean;
  onChange: (sceneId: string) => void;
  onRename: (sceneId: string, title: string) => Promise<void>;
  onDelete: (sceneId: string) => void;
  onNewScene: () => void;
  canManage?: boolean;
}) {
  const root = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [renameError, setRenameError] = useState("");
  const [saving, setSaving] = useState(false);
  const [menuId, setMenuId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const current = scenes.find((scene) => scene.id === sceneId) ?? null;
  const needle = query.trim().toLowerCase();
  const visible = needle ? scenes.filter((scene) => scene.title.toLowerCase().includes(needle)) : scenes;

  useEffect(() => {
    if (!open) return;
    function close(event: PointerEvent) {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [open]);

  function closePanel() {
    setOpen(false);
    setQuery("");
    setEditingId(null);
    setMenuId(null);
    setDeletingId(null);
    setRenameError("");
  }

  function beginRename(scene: SceneChoice) {
    setEditingId(scene.id);
    setDraft(scene.title);
    setRenameError("");
    setMenuId(null);
    setDeletingId(null);
  }

  async function saveRename(scene: SceneChoice) {
    const title = draft.trim();
    if (!title) {
      setRenameError("名称不能为空");
      return;
    }
    setSaving(true);
    try {
      await onRename(scene.id, title);
      setEditingId(null);
      setRenameError("");
    } catch (reason) {
      setRenameError(reason instanceof Error ? reason.message : "无法保存名称");
    } finally {
      setSaving(false);
    }
  }

  return <div className="scene-selector" ref={root}>
    <button
      type="button"
      className="scene-selector-current"
      aria-haspopup="listbox"
      aria-expanded={open}
      title={current ? `${current.title}${current.ready ? " · 已准备" : " · 尚未构建"}` : "选择场景"}
      onClick={() => setOpen((value) => !value)}
    >
      {current && !current.ready && <i className="pending" title="尚未构建" />}
      <span>{current?.title ?? "选择场景"}</span>
      <b aria-hidden="true">▼</b>
    </button>
    {canManage && <button type="button" onClick={onNewScene}>+ 新建场景</button>}
    {open && <div className="scene-selector-panel" role="listbox" aria-label="场景列表">
      <div className="scene-selector-head">
        <strong>场景管理</strong>
      </div>
      <input
        aria-label="搜索场景名称"
        placeholder="搜索场景名称"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      <div className="scene-selector-list">
        {visible.length === 0 && <p>{scenes.length === 0 ? "还没有场景。" : "没有匹配的场景。"}</p>}
        {visible.map((scene) => <div key={scene.id} className={["scene-selector-row", scene.id === sceneId ? "active" : "", menuId === scene.id ? "menu-open" : ""].filter(Boolean).join(" ")}>
          {deletingId === scene.id ? <div className="scene-delete-confirm" role="group" aria-label={`确认删除 ${scene.title}`}>
            <em>删除「{scene.title}」？</em>
            <button type="button" onClick={() => { setDeletingId(null); onDelete(scene.id); }}>删除</button>
            <button type="button" onClick={() => setDeletingId(null)}>取消</button>
          </div> : editingId === scene.id ? <form onSubmit={(event) => { event.preventDefault(); void saveRename(scene); }}>
            <input
              aria-label={`场景名称 ${scene.title}`}
              value={draft}
              autoFocus
              disabled={saving}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Escape") {
                  event.preventDefault();
                  setEditingId(null);
                  setRenameError("");
                }
              }}
            />
            <button type="submit" aria-label="保存名称" disabled={saving}>✓</button>
            <button type="button" aria-label="取消重命名" onClick={() => { setEditingId(null); setRenameError(""); }}>×</button>
            {renameError && <em role="alert">{renameError}</em>}
          </form> : <>
            <button
              type="button"
              disabled={disabled}
              title={scene.ready ? `${scene.title} · 已准备` : `${scene.title} · 尚未构建`}
              onClick={() => { onChange(scene.id); closePanel(); }}
            >
              <span className="scene-selector-mark" aria-hidden="true">{scene.id === sceneId ? "✓" : ""}</span>
              <span>{scene.title}</span>
              {!scene.ready && <i className="pending" title="尚未构建" />}
            </button>
            {canManage && <span className="scene-selector-actions">
              <button type="button" aria-label={`重命名 ${scene.title}`} title="重命名" onClick={(event) => { event.stopPropagation(); beginRename(scene); }}>✎</button>
              <button type="button" aria-label={`${scene.title} 的更多操作`} title="更多操作" onClick={(event) => { event.stopPropagation(); setMenuId((value) => value === scene.id ? null : scene.id); }}>⋯</button>
            </span>}
            {canManage && menuId === scene.id && <div className="scene-selector-menu" role="menu">
              <button type="button" role="menuitem" onClick={() => beginRename(scene)}>重命名</button>
              {scene.id === sceneId ? <>
                <button type="button" role="menuitem" aria-disabled="true" onClick={() => onDelete(scene.id)}>删除场景</button>
                <p>当前场景正在使用，请先切换到其他场景后再删除。</p>
              </> : <button
                type="button"
                role="menuitem"
                disabled={disabled}
                title={`删除场景 ${scene.title}`}
                onClick={() => { setMenuId(null); setDeletingId(scene.id); }}
              >
                删除场景
              </button>}
            </div>}
          </>}
        </div>)}
      </div>
    </div>}
  </div>;
}
