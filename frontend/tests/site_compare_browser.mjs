import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { existsSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";

const browser = process.argv[2];
if (!browser) throw new Error("Pass a Chromium-compatible browser path");
const tempRoot = realpathSync(tmpdir());
const profile = realpathSync(mkdtempSync(join(tempRoot, "site-compare-browser-")));
const child = spawn(browser, ["--headless", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--no-first-run", "--disable-extensions",
  "--remote-debugging-port=0", `--user-data-dir=${profile}`, "--window-size=1000,700",
  `${process.argv[3] ?? "http://127.0.0.1:5178"}/tests/site_compare_browser.html`], { windowsHide: true, stdio: "ignore" });
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
let socket;
let call;
try {
  const portFile = join(profile, "DevToolsActivePort");
  for (let i = 0; i < 100 && !existsSync(portFile); i++) await delay(100);
  assert.ok(existsSync(portFile), "Browser debugging endpoint did not start");
  const port = readFileSync(portFile, "utf8").split("\n")[0];
  const pages = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const page = pages.find((item) => item.type === "page");
  assert.ok(page, "Browser page is missing");
  socket = new WebSocket(page.webSocketDebuggerUrl);
  await once(socket, "open");
  const pending = new Map();
  let id = 0;
  call = (method, params = {}) => new Promise((resolve, reject) => {
    pending.set(++id, { resolve, reject }); socket.send(JSON.stringify({ id, method, params }));
  });
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data), request = pending.get(message.id);
    if (!request) return;
    pending.delete(message.id);
    if (message.error) request.reject(new Error(message.error.message)); else request.resolve(message.result);
  });
  socket.addEventListener("close", () => { for (const request of pending.values()) request.reject(new Error("Browser closed")); pending.clear(); });
  let outcome;
  for (let i = 0; i < 200; i++) {
    const result = await call("Runtime.evaluate", { expression: "document.body.dataset.result", returnByValue: true });
    outcome = result.result.value;
    if (outcome) break;
    await delay(100);
  }
  if (process.argv[4]) {
    const screenshot = await call("Page.captureScreenshot", { format: "png" });
    writeFileSync(process.argv[4], Buffer.from(screenshot.data, "base64"));
  }
  assert.equal(outcome, "PASS", outcome ?? "Real map render timed out");
} finally {
  if (call) await call("Browser.close").catch(() => {});
  socket?.close();
  for (let i = 0; i < 30 && child.exitCode === null; i++) await delay(100);
  if (child.exitCode === null) child.kill();
  const resolved = realpathSync(profile);
  if (resolved !== profile || dirname(resolved) !== tempRoot) throw new Error("Unexpected browser profile path");
  rmSync(resolved, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
}
console.log("Site comparison: real MapLibre colors, old-map style synchronization, removal and filtering passed");
