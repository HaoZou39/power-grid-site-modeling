import { useEffect, useMemo, useState } from "react";
import { createJob, getHealth, getJob, getPlugins, JobRecord, PluginSpec } from "./api";

function App() {
  const [health, setHealth] = useState("检查中...");
  const [plugins, setPlugins] = useState<PluginSpec[]>([]);
  const [selectedPlugin, setSelectedPlugin] = useState("demo.algorithm");
  const [values, setValues] = useState("1, 2, 3");
  const [multiplier, setMultiplier] = useState("1");
  const [job, setJob] = useState<JobRecord | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([getHealth(), getPlugins()])
      .then(([status, catalog]) => {
        setHealth(`${status.service} ${status.version} · ${status.status}`);
        setPlugins(catalog.items);
      })
      .catch((reason: Error) => setError(reason.message));
  }, []);

  useEffect(() => {
    if (!job || job.status === "succeeded" || job.status === "failed") return;
    const timer = window.setInterval(() => {
      getJob(job.job_id).then(setJob).catch((reason: Error) => setError(reason.message));
    }, 700);
    return () => window.clearInterval(timer);
  }, [job]);

  const selected = useMemo(() => plugins.find((plugin) => plugin.id === selectedPlugin), [plugins, selectedPlugin]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    try {
      const config = {
        values: values.split(",").map((item) => Number(item.trim())),
        multiplier: Number(multiplier),
      };
      setJob(await createJob({ plugin_id: selectedPlugin, config }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "提交失败");
    }
  }

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">温州电力设计院 · V0.1</p>
          <h1>电力选址建模平台</h1>
        </div>
        <span className="health">● {health}</span>
      </header>
      <section className="grid">
        <article className="card">
          <p className="eyebrow">PLUGIN CATALOG</p>
          <h2>可用插件</h2>
          {plugins.length === 0 ? <p className="muted">正在加载插件...</p> : plugins.map((plugin) => (
            <button className={`plugin ${selectedPlugin === plugin.id ? "selected" : ""}`} key={plugin.id} onClick={() => setSelectedPlugin(plugin.id)}>
              <strong>{plugin.name}</strong>
              <span>{plugin.id} · v{plugin.version}</span>
              <small>{plugin.description}</small>
            </button>
          ))}
        </article>
        <article className="card">
          <p className="eyebrow">JOB SUBMISSION</p>
          <h2>提交演示任务</h2>
          <p className="muted">当前插件：{selected?.name ?? selectedPlugin}</p>
          <form onSubmit={submit}>
            <label>数值列表<input value={values} onChange={(event) => setValues(event.target.value)} /></label>
            <label>乘数<input value={multiplier} onChange={(event) => setMultiplier(event.target.value)} /></label>
            <button className="primary" type="submit">提交任务</button>
          </form>
          {error && <p className="error">{error}</p>}
        </article>
        <article className="card result-card">
          <p className="eyebrow">JOB STATUS</p>
          <h2>任务状态</h2>
          {!job ? <p className="muted">提交任务后在这里查看状态。</p> : <>
            <div className="job-id">{job.job_id}</div>
            <div className="progress"><span style={{ width: `${job.progress * 100}%` }} /></div>
            <p><strong>{job.status}</strong> · {job.stage}</p>
            <p className="muted">{job.message}</p>
            {job.result && <pre>{JSON.stringify(job.result, null, 2)}</pre>}
            {job.error && <pre className="error">{JSON.stringify(job.error, null, 2)}</pre>}
          </>}
        </article>
      </section>
    </main>
  );
}

export default App;
