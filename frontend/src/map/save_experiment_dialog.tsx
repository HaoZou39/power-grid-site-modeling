import { useState } from "react";

export function SaveExperimentDialog({ count, busy, error, onClose, onSave }: {
  count: number; busy: boolean; error: string;
  onClose: () => void; onSave: (name: string) => void;
}) {
  const [name, setName] = useState("");
  return <div className="scene-build-backdrop" onClick={() => { if (!busy) onClose(); }}>
    <section className="scene-build-dialog" role="dialog" aria-modal="true" aria-label="另存当前实验"
      onClick={(event) => event.stopPropagation()} onKeyDown={(event) => { if (event.key === "Escape" && !busy) onClose(); }}>
      <form onSubmit={(event) => { event.preventDefault(); onSave(name); }}>
        <div className="scene-build-head"><h2>另存当前实验</h2>
          <button type="button" disabled={busy} onClick={onClose}>关闭</button></div>
        <div className="scene-build-body">
          <label>实验名称<input autoFocus value={name} maxLength={120} disabled={busy}
            onChange={(event) => setName(event.target.value)} placeholder="例如：楠溪江筛选结果" /></label>
          <p>保存全部 {count} 个保留方案，包含暂时隐藏的方案，不含已删除方案。</p>
          <p className="hud-note">保存后可从「导入案例」重新打开。同名保存会新建案例。</p>
          {busy && <p role="status">正在评价并保存方案，请稍候…</p>}
          {error && <p className="scene-build-error" role="alert">{error}</p>}
        </div>
        <div className="scene-build-actions"><button type="button" disabled={busy} onClick={onClose}>取消</button>
          <button type="submit" className="primary" disabled={busy || !name.trim() || !count}>保存实验</button></div>
      </form>
    </section>
  </div>;
}
