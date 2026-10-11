import { useEffect, useMemo, useState, type FormEvent } from "react";

import { createJob, getExperiments, getPlugins } from "./api";
import type { PluginSpec } from "./api";
import { checkConfig, hasSitingFields } from "./config_check";
import { ConfigForm, normalizeConfig, schemaDefaults } from "./config_form";
import type { ConfigObject } from "./config_form";
import { selectProblemArtifacts } from "./problem_snapshot";
import { RunMonitor } from "./run_monitor";

type SubmittedRun = {
  jobId: string;
  pluginId: string;
  pluginName: string;
  config: Record<string, unknown>;
};

/**
 * Plugin selection and submission live here. Job polling lives only in RunMonitor.
 */
export function JobWorkspace() {
  const [plugins, setPlugins] = useState<PluginSpec[]>([]);
  const [selectedPluginId, setSelectedPluginId] = useState("demo.algorithm");
  const [config, setConfig] = useState<ConfigObject>({});
  const [submitted, setSubmitted] = useState<SubmittedRun | null>(null);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [allowOverwrite, setAllowOverwrite] = useState(false);
  const [experimentIds, setExperimentIds] = useState<string[]>([]);

  const selectedPlugin = useMemo(
    () => plugins.find((plugin) => plugin.id === selectedPluginId),
    [plugins, selectedPluginId],
  );

  // Load the plugin catalog once. The schema is the single source of truth for the form.
  useEffect(() => {
    getPlugins()
      .then((catalog) => {
        setPlugins(catalog.items);
        const firstPlugin = catalog.items.find((plugin) => plugin.id === selectedPluginId) ?? catalog.items[0];
        if (firstPlugin) {
          setSelectedPluginId(firstPlugin.id);
          setConfig(schemaDefaults(firstPlugin.config_schema));
        }
      })
      .catch((reason: Error) => setError(reason.message));
    getExperiments()
      .then((items) => setExperimentIds(items.map((item) => item.id)))
      .catch(() => setExperimentIds([]));
  }, []);

  useEffect(() => {
    if (selectedPlugin) setConfig(schemaDefaults(selectedPlugin.config_schema));
  }, [selectedPlugin]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setFieldErrors({});
    try {
      if (!selectedPlugin) throw new Error("插件尚未加载");
      const dataMissing = hasSitingFields(selectedPlugin.config_schema) ? await missingDataProducts() : [];
      const issues = checkConfig(selectedPlugin.config_schema, config, {
        existingExperimentIds: experimentIds,
        allowOverwrite: allowOverwrite || config.overwrite_existing === true,
        dataMissing,
      });
      if (issues.length > 0) {
        setFieldErrors(Object.fromEntries(issues.filter((issue) => issue.path).map((issue) => [issue.path, issue.message])));
        setError(issues.find((issue) => issue.path === "")?.message ?? "");
        return;
      }
      const normalized = normalizeConfig(selectedPlugin.config_schema, config);
      await startRun(selectedPlugin.id, selectedPlugin.name, normalized);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "提交失败");
    }
  }

  async function startRun(pluginId: string, pluginName: string, payload: Record<string, unknown>) {
    const job = await createJob({ plugin_id: pluginId, config: payload });
    setSubmitted({ jobId: job.job_id, pluginId, pluginName, config: payload });
  }

  async function rerun() {
    if (!submitted) return;
    setError("");
    try {
      await startRun(submitted.pluginId, submitted.pluginName, submitted.config);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "重新运行失败");
    }
  }

  function returnToConfig() {
    document.getElementById("run-config")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return (
    <>
    <section className="workspace-grid">
      <PluginCatalog
        plugins={plugins}
        selectedPluginId={selectedPluginId}
        onSelect={setSelectedPluginId}
      />
      <JobSubmission
        plugin={selectedPlugin}
        config={config}
        error={error}
        fieldErrors={fieldErrors}
        allowOverwrite={allowOverwrite}
        onAllowOverwrite={setAllowOverwrite}
        showOverwrite={typeof config.experiment_name === "string" && experimentIds.includes(config.experiment_name)}
        onConfigChange={(next) => {
          setConfig(next);
          setFieldErrors({});
        }}
        onSubmit={submit}
      />
    </section>
    <RunMonitor
      jobId={submitted?.jobId ?? null}
      config={submitted?.config ?? null}
      pluginName={submitted?.pluginName ?? ""}
      onReturnToConfig={returnToConfig}
      onRerun={() => void rerun()}
    />
    </>
  );
}

function PluginCatalog({
  plugins,
  selectedPluginId,
  onSelect,
}: {
  plugins: PluginSpec[];
  selectedPluginId: string;
  onSelect: (pluginId: string) => void;
}) {
  return (
    <article className="card">
      <p className="eyebrow">PLUGIN CATALOG</p>
      <h2>可用插件</h2>
      {plugins.length === 0 ? <p className="muted">正在加载插件...</p> : plugins.map((plugin) => (
        <button
          className={`plugin ${selectedPluginId === plugin.id ? "selected" : ""}`}
          key={plugin.id}
          onClick={() => onSelect(plugin.id)}
        >
          <strong>{plugin.name}</strong>
          <span>{plugin.id} · v{plugin.version}</span>
          <small>{plugin.description}</small>
        </button>
      ))}
    </article>
  );
}

function JobSubmission({
  plugin,
  config,
  error,
  fieldErrors,
  allowOverwrite,
  showOverwrite,
  onAllowOverwrite,
  onConfigChange,
  onSubmit,
}: {
  plugin: PluginSpec | undefined;
  config: ConfigObject;
  error: string;
  fieldErrors: Record<string, string>;
  allowOverwrite: boolean;
  showOverwrite: boolean;
  onAllowOverwrite: (value: boolean) => void;
  onConfigChange: (value: ConfigObject) => void;
  onSubmit: (event: FormEvent) => void;
}) {
  return (
    <article className="card" id="run-config">
      <p className="eyebrow">步骤 2</p>
      <h2>配置与运行</h2>
      <p className="muted">当前算法：{plugin?.name ?? "加载中"}。这里的检查通过后仍由后端做最终校验。</p>
      <form onSubmit={onSubmit}>
        {plugin && <ConfigForm schema={plugin.config_schema} value={config} errors={fieldErrors} onChange={onConfigChange} />}
        {showOverwrite && (
          <label className="checkbox-label">
            <input type="checkbox" checked={allowOverwrite} onChange={(event) => onAllowOverwrite(event.target.checked)} />
            覆盖已有同名实验结果
          </label>
        )}
        <button className="primary" type="submit">开始运行</button>
      </form>
      {error && <p className="error">{error}</p>}
    </article>
  );
}

async function missingDataProducts(): Promise<string[]> {
  const experiments = await getExperiments();
  const ready = experiments.some((experiment) => {
    const selected = selectProblemArtifacts(experiment.artifacts);
    return selected.metadataUrl && selected.configUrl;
  });
  if (ready) return [];
  return ["data_metadata.json", "resolved_config.json"];
}
