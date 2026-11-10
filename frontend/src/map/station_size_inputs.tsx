import { useState } from "react";
import defaults from "../../../config/default_config.json";

type AreaBasis = "red_line" | "inside_wall";
const schemes: Record<string, Record<AreaBasis, number[]>> = defaults.modeling.station_schemes;

export function StationSizeInputs({ length, width, ready, onChange }: {
  length: string;
  width: string;
  ready: boolean;
  onChange: (length: string, width: string) => void;
}) {
  const [basis, setBasis] = useState<AreaBasis>("red_line");
  const selected = Object.keys(schemes).find((name) => {
    const size = schemes[name][basis];
    return Number(length) === size[0] && Number(width) === size[1];
  }) ?? "";
  const valid = Number(length) > 0 && Number(width) > 0 && Number.isFinite(Number(length) * Number(width));
  const note = !ready
    ? "正在读取默认占地尺寸"
    : !valid
      ? "请输入有效长宽。"
      : selected
        ? null
        : "当前为自定义尺寸，请选择方案以填入对应口径的长宽。";

  function applyScheme(name: string, nextBasis: AreaBasis) {
    const size = schemes[name][nextBasis];
    onChange(String(size[0]), String(size[1]));
  }

  return <>
    <label>方案名称
      <select value={selected} disabled={!ready} onChange={(event) => applyScheme(event.target.value, basis)}>
        <option value="" disabled>自定义尺寸</option>
        {Object.keys(schemes).map((name) => <option key={name} value={name}>{name}</option>)}
      </select>
    </label>
    <label>优化占地口径
      <select value={basis} disabled={!ready} onChange={(event) => {
        const nextBasis = event.target.value as AreaBasis;
        setBasis(nextBasis);
        if (selected) applyScheme(selected, nextBasis);
      }}>
        <option value="red_line">变电站红线面积（围墙外扩 1.5 m）</option>
        <option value="inside_wall">围墙内占地面积</option>
      </select>
    </label>
    <label>变电站长度（m）<input value={length} onChange={(event) => onChange(event.target.value, width)} /></label>
    <label>变电站宽度（m）<input value={width} onChange={(event) => onChange(length, event.target.value)} /></label>
    {note && <p className="hud-note">{note}</p>}
  </>;
}
