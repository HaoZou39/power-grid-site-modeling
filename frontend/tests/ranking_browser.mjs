import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, realpathSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";

const browser = process.argv[2];
if (!browser) throw new Error("Pass a Chromium-compatible browser path");
const baseUrl = process.argv[3] ?? "http://127.0.0.1:5176";
const tempRoot = realpathSync(tmpdir());
for (const query of ["", "?narrow=1", "?site=1", "?site=1&narrow=1"]) {
  const profile = realpathSync(mkdtempSync(join(tempRoot, "ranking-browser-")));
  try {
    const result = spawnSync(browser, ["--headless", "--disable-gpu", "--no-first-run", "--disable-extensions",
      `--user-data-dir=${profile}`, "--window-size=1500,1100", "--virtual-time-budget=8000", "--dump-dom",
      ...(process.argv[4] ? [`--screenshot=${process.argv[4]}`] : []),
      `${baseUrl}/tests/ranking_browser.html${query}`], { encoding: "utf8", timeout: 30000, windowsHide: true });
    if (result.error) throw result.error;
    const outcome = /data-result="([^"]*)"/.exec(result.stdout)?.[1];
    assert.equal(outcome, "PASS", `${query || "wide"}: ${outcome ?? result.stderr.slice(-1000)}`);
  } finally {
    const resolved = realpathSync(profile);
    if (resolved !== profile || dirname(resolved) !== tempRoot) throw new Error("Unexpected browser profile path");
    rmSync(resolved, { recursive: true, force: true });
  }
}
console.log("Ranking browser: site and routing retained map sets, expanded distribution, dark controls and record actions passed at both widths");
