import { useEffect, useState } from "react";
import { SettingsRequestError, readAgentSettings, writeAgentSettings } from "./agent_settings_api.js";
import type { AgentSettings } from "./agent_settings_api.js";
import {
  MEMORY_DISABLED_NOTE,
  MEMORY_ENABLED_NOTE,
  MODEL_SAVED,
  canSaveModel,
  configSourceLabel,
  keyPlaceholder,
} from "./agent_settings_form.js";

export function AgentSettingsDialog({
  open,
  onClose,
  onMemoryDisabled,
}: {
  open: boolean;
  onClose: () => void;
  onMemoryDisabled: () => void;
}) {
  const [settings, setSettings] = useState<AgentSettings | null>(null);
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [password, setPassword] = useState("");
  const [clearKey, setClearKey] = useState(false);
  const [showKey, setShowKey] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [baseUrlError, setBaseUrlError] = useState("");
  const [modelError, setModelError] = useState("");
  const [apiKeyError, setApiKeyError] = useState("");
  const [modelNote, setModelNote] = useState("");
  const [memoryNote, setMemoryNote] = useState("");
  const [memoryError, setMemoryError] = useState("");
  const [confirmDisable, setConfirmDisable] = useState(false);

  useEffect(() => {
    if (!open) {
      setPassword("");
      setApiKey("");
      setClearKey(false);
      setBaseUrlError("");
      setModelError("");
      setApiKeyError("");
      setModelNote("");
      setMemoryNote("");
      setMemoryError("");
      setLoadError("");
      setConfirmDisable(false);
      setSettings(null);
      return;
    }
    let active = true;
    setLoadError("");
    readAgentSettings().then(
      (next) => {
        if (!active) return;
        applySettings(next);
      },
      (reason) => {
        if (active) setLoadError(reason instanceof Error ? reason.message : "设置读取失败");
      },
    );
    return () => { active = false; };
  }, [open]);

  function applySettings(next: AgentSettings) {
    setSettings(next);
    setBaseUrl(next.base_url);
    setModel(next.model);
    setApiKey("");
    setPassword("");
    setClearKey(false);
    setShowKey(false);
  }

  function showFailure(reason: unknown) {
    const error = reason instanceof SettingsRequestError
      ? reason
      : new SettingsRequestError(reason instanceof Error ? reason.message : "设置操作失败");
    if (error.field === "base_url") setBaseUrlError(error.message);
    else if (error.field === "model") setModelError(error.message);
    else if (error.field === "api_key") setApiKeyError(error.message);
    else setModelError(error.message);
  }

  async function submitModel() {
    setBusy(true);
    setBaseUrlError("");
    setModelError("");
    setApiKeyError("");
    setModelNote("");
    setMemoryNote("");
    setMemoryError("");
    try {
      const next = await writeAgentSettings({
        action: "update_model",
        password,
        base_url: baseUrl,
        model,
        api_key: apiKey.trim() || undefined,
        clear_api_key: clearKey,
      });
      applySettings(next);
      setModelNote(MODEL_SAVED);
    } catch (reason) {
      showFailure(reason);
    } finally {
      setBusy(false);
    }
  }

  function saveModel() {
    if (!canSaveModel(busy)) return;
    void submitModel();
  }

  async function changeMemory(action: "enable_memory" | "disable_memory_and_clear"): Promise<boolean> {
    if (busy) return false;
    setBusy(true);
    setModelNote("");
    setMemoryNote("");
    setMemoryError("");
    try {
      const next = await writeAgentSettings({ action });
      applySettings(next);
      setConfirmDisable(false);
      if (action === "enable_memory") setMemoryNote(MEMORY_ENABLED_NOTE);
      else {
        setMemoryNote(MEMORY_DISABLED_NOTE);
        onMemoryDisabled();
      }
      return true;
    } catch (reason) {
      const error = reason instanceof SettingsRequestError
        ? reason
        : new SettingsRequestError(reason instanceof Error ? reason.message : "长期记忆设置失败");
      if (error.field === undefined) setMemoryError(error.message);
      else showFailure(reason);
      try {
        const fresh = await readAgentSettings();
        setSettings(fresh);
      } catch {
        // Keep the last confirmed toggle if refreshing also fails.
      }
      return false;
    } finally {
      setBusy(false);
    }
  }

  if (!open) return null;
  const saveEnabled = canSaveModel(busy);
  return (
    <section className="agent-settings-dialog" role="dialog" aria-modal="true" aria-labelledby="agent-settings-title">
      <div className="agent-settings-head">
        <strong id="agent-settings-title">AI 助手设置</strong>
        <button type="button" onClick={onClose}>关闭</button>
      </div>
      {!settings && !loadError ? <p className="agent-settings-hint">正在读取设置…</p> : null}
      {loadError ? <p className="agent-settings-error">{loadError}</p> : null}
      {settings && (
        <>
          <section className="agent-settings-section">
            <strong>模型 API 配置</strong>
            <p className="agent-settings-source">{configSourceLabel(settings.config_source)}</p>
            {settings.external_notice ? <p className="agent-settings-hint">{settings.external_notice}</p> : null}
            <label>API Base URL
              <input
                type="text"
                value={baseUrl}
                disabled={busy || !settings.base_url_editable}
                aria-invalid={baseUrlError !== ""}
                onChange={(event) => {
                  setBaseUrl(event.target.value);
                  setBaseUrlError("");
                  setModelNote("");
                }}
              />
            </label>
            {baseUrlError ? <p className="agent-settings-error">{baseUrlError}</p> : null}
            <label>Model
              <input
                type="text"
                value={model}
                disabled={busy}
                aria-invalid={modelError !== ""}
                onChange={(event) => {
                  setModel(event.target.value);
                  setModelError("");
                  setModelNote("");
                }}
              />
            </label>
            {modelError ? <p className="agent-settings-error">{modelError}</p> : null}
            <label>API Key
              <span className="agent-key-input">
                <input
                  type={showKey ? "text" : "password"}
                  value={apiKey}
                  autoComplete="new-password"
                  disabled={busy}
                  placeholder={keyPlaceholder(settings.api_key_configured)}
                  aria-invalid={apiKeyError !== ""}
                  onChange={(event) => {
                    setApiKey(event.target.value);
                    setApiKeyError("");
                    setModelNote("");
                  }}
                />
                <button type="button" onClick={() => setShowKey((shown) => !shown)}>{showKey ? "隐藏" : "显示"}</button>
              </span>
            </label>
            {apiKeyError ? <p className="agent-settings-error">{apiKeyError}</p> : null}
            <label><input type="checkbox" checked={clearKey} disabled={busy || !settings.api_key_editable}
              onChange={(event) => { setClearKey(event.target.checked); if (event.target.checked) setApiKey(""); }} />清除旧 API Key</label>
            <p className="hud-note">更改 API 地址时，请填写新密钥或明确清除旧密钥。</p>
            <label>管理员密码<input type="password" autoComplete="current-password" value={password}
              disabled={busy} onChange={(event) => setPassword(event.target.value)} /></label>
            <button type="button" className="primary" disabled={!saveEnabled || !password} onClick={saveModel}>保存模型配置</button>
            {modelNote ? <p className="agent-settings-ok">{modelNote}</p> : null}
          </section>
          <section className="agent-settings-section">
            <div className="agent-settings-row">
              <span>
                <strong>长期记忆</strong>
                <small>允许 AI 助手跨会话记住用户偏好、常用指令和场景信息。</small>
              </span>
              <button
                type="button"
                className={settings.memory_enabled ? "settings-toggle active" : "settings-toggle"}
                aria-pressed={settings.memory_enabled}
                disabled={busy}
                onClick={() => {
                  if (settings.memory_enabled) setConfirmDisable(true);
                  else void changeMemory("enable_memory");
                }}
              >
                {settings.memory_enabled ? "开启" : "关闭"}
              </button>
            </div>
            <p className="agent-settings-hint">关闭将清除文字记忆，不影响方案偏好学习。</p>
            {memoryNote ? <p className="agent-settings-ok">{memoryNote}</p> : null}
            {memoryError ? <p className="agent-settings-error">{memoryError}</p> : null}
          </section>
        </>
      )}
      {confirmDisable && (
        <div className="agent-settings-confirm" role="alertdialog" aria-labelledby="memory-disable-title">
          <strong id="memory-disable-title">关闭并清除长期记忆？</strong>
          <p>关闭后将永久清除 AI 保存的文字记忆，且不会继续读取或保存新的文字记忆。此操作无法撤销，方案偏好学习不受影响。</p>
          <div className="hud-actions">
            <button type="button" disabled={busy} onClick={() => setConfirmDisable(false)}>取消</button>
            <button type="button" className="danger" disabled={busy} onClick={() => void changeMemory("disable_memory_and_clear")}>关闭并清除</button>
          </div>
        </div>
      )}
    </section>
  );
}
