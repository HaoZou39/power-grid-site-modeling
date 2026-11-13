import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, realpathSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, sep } from "node:path";

const browser = process.argv[2];
if (!browser) throw new Error("Pass the path to a Chromium-compatible browser as the first argument");
const baseUrl = process.argv[3] ?? "http://127.0.0.1:5176";
const tempRoot = realpathSync(tmpdir());
for (const [blocked, delayed] of [[0, 0], [1, 0], [0, 1]]) {
  const profile = realpathSync(mkdtempSync(join(tempRoot, "scheme-panel-browser-")));
  if (dirname(profile) !== tempRoot || !profile.startsWith(tempRoot + sep)) throw new Error("Invalid temporary browser profile");
  try {
    const result = spawnSync(browser, [
      "--headless", "--disable-gpu", "--no-first-run", "--disable-extensions",
      `--user-data-dir=${profile}`, "--window-size=1500,1000", "--virtual-time-budget=6000", "--dump-dom",
      `${baseUrl}/tests/scheme_panel_browser.html?blocked=${blocked}${delayed ? "&delayed" : ""}`,
    ], { encoding: "utf8", timeout: 30000, windowsHide: true });
    if (result.error) throw result.error;
    const outcome = /data-result="([^"]*)"/.exec(result.stdout)?.[1];
    assert.equal(outcome, "PASS", `Browser fixture failed (blocked=${blocked}, delayed=${delayed}): ${outcome ?? result.stderr.slice(-500)}`);
  } finally {
    const resolvedProfile = realpathSync(profile);
    if (resolvedProfile !== profile || dirname(resolvedProfile) !== tempRoot) throw new Error("Browser profile path changed");
    rmSync(resolvedProfile, { recursive: true, force: true });
  }
}
console.log("scheme panel browser: fresh placement after selection, panel drag and map drag passed");
