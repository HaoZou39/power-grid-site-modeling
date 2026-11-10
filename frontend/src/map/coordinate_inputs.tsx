import { useState } from "react";
import type { LngLat } from "./site_frame";

export type CoordinateInputsProps = {
  value: LngLat | null;
  resetKey: string;
  disabled: boolean;
  onConfirm: (longitude: string, latitude: string) => void;
};

export function CoordinateInputs(props: CoordinateInputsProps) {
  // Reset drafts on a different target or position, not on metric refreshes.
  const identity = JSON.stringify([props.resetKey, props.value?.lng, props.value?.lat]);
  return <CoordinateDraft key={identity} {...props} />;
}

function CoordinateDraft({ value, disabled, onConfirm }: CoordinateInputsProps) {
  const [longitude, setLongitude] = useState(value ? String(value.lng) : "");
  const [latitude, setLatitude] = useState(value ? String(value.lat) : "");
  const [error, setError] = useState("");

  // The step controls arrows only; manual input may contain more decimal places.
  return <form className="coordinate-form" noValidate onSubmit={(event) => {
    event.preventDefault();
    if (disabled) return;
    try { onConfirm(longitude, latitude); setError(""); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "无法应用坐标。"); }
  }}>
    <div className="coordinate-fields">
      <label>经度（°）<input type="number" step="0.000001" value={longitude} onChange={(event) => setLongitude(event.target.value)} disabled={disabled} /></label>
      <label>纬度（°）<input type="number" step="0.000001" value={latitude} onChange={(event) => setLatitude(event.target.value)} disabled={disabled} /></label>
    </div>
    {error && <p className="hud-evaluation error" role="alert">{error}</p>}
    <div className="hud-actions"><button type="submit" disabled={disabled}>确定坐标</button></div>
  </form>;
}
