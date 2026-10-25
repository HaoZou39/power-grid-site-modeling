import { useEffect, useRef, useState } from "react";

/** Typing commits once; arrow keys and the native spinner commit their completed step. */
export function SetbackInput({ value, onCommit }: { value: number; onCommit: (value: number) => void }) {
  const [draft, setDraft] = useState(String(value));
  const [focused, setFocused] = useState(false);
  const pointerStart = useRef<string | null>(null);
  useEffect(() => { if (!focused) setDraft(String(value)); }, [value, focused]);

  function commit(input: HTMLInputElement) {
    const next = Number(input.value);
    if (!input.value.trim() || !Number.isFinite(next) || next < 0) {
      input.setCustomValidity("退距必须是大于或等于 0 的有限数字。");
      input.reportValidity();
      setDraft(String(value));
      return;
    }
    input.setCustomValidity("");
    if (next !== value) onCommit(next);
  }

  return <input type="number" min={0} step="1" value={draft}
    onFocus={() => setFocused(true)}
    onChange={(event) => { event.target.setCustomValidity(""); setDraft(event.target.value); }}
    onBlur={(event) => { commit(event.currentTarget); setFocused(false); }}
    onPointerDown={(event) => { pointerStart.current = event.currentTarget.value; }}
    onPointerUp={(event) => {
      if (pointerStart.current !== null && pointerStart.current !== event.currentTarget.value) commit(event.currentTarget);
      pointerStart.current = null;
    }}
    onKeyDown={(event) => {
      if (event.key === "Enter") event.currentTarget.blur();
      if (event.key === "ArrowUp" || event.key === "ArrowDown") {
        event.preventDefault();
        const parsed = Number(draft);
        const next = Math.max(0, (Number.isFinite(parsed) ? parsed : value) + (event.key === "ArrowUp" ? 1 : -1));
        setDraft(String(next));
        if (next !== value) onCommit(next);
      }
    }} />;
}
