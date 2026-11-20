import assert from "node:assert/strict";
import test from "node:test";
import { CompletionAlert, optimizationReminder } from "../../.tmp-problem-snapshot/map/completion_alert.js";

const PAGE = "电力选址建模平台";

function harness(patch = {}) {
  const titles = [];
  const calls = { notify: [], beep: 0, arm: 0, request: 0 };
  const timers = [];
  let now = 0;
  let permission = "default";
  let secure = false;
  const host = {
    get secure() { return secure; },
    get permission() { return permission; },
    requestPermission: async () => { calls.request += 1; permission = "granted"; return permission; },
    notify: (title, body) => { calls.notify.push([title, body]); },
    title: () => titles.at(-1) ?? PAGE,
    setTitle: (value) => titles.push(value),
    arm: () => { calls.arm += 1; },
    beep: () => { calls.beep += 1; },
    schedule: (fn, ms) => { const id = timers.push({ fn, at: now + ms }) - 1; return id; },
    cancel: (id) => { timers[id].fn = null; },
  };
  Object.assign(host, patch.host ?? {});
  if (patch.secure !== undefined) secure = patch.secure;
  if (patch.permission !== undefined) permission = patch.permission;
  const alert = new CompletionAlert(host);
  return {
    alert, titles, calls,
    advance(ms) {
      const end = now + ms;
      for (;;) {
        const due = timers.filter((timer) => timer.fn && timer.at <= end).sort((a, b) => a.at - b.at)[0];
        if (!due) break;
        now = due.at;
        const fn = due.fn;
        due.fn = null;
        fn();
      }
      now = end;
    },
  };
}

test("reminder wording follows the search kind and terminal status", () => {
  assert.deepEqual(optimizationReminder("search", "succeeded", "已给出 3 个可行方案。"), {
    title: "优化完成", body: "已给出 3 个可行方案。",
  });
  assert.equal(optimizationReminder("refine", "succeeded", "局部优化完成：加入方案 2。").title, "局部优化完成");
  assert.equal(optimizationReminder("search", "failed", "运行失败").title, "优化失败");
  assert.equal(optimizationReminder("refine", "failed", "运行失败").title, "局部优化失败");
  assert.equal(optimizationReminder("search", "cancelled", "这次优化已停止，没有新方案。").title, "优化已取消");
  assert.equal(optimizationReminder("refine", "cancelled", "这次局部优化已停止，原方案仍在。").title, "局部优化已取消");
});

test("an insecure page blinks the tab and beeps once", () => {
  const h = harness();
  assert.equal(h.alert.finish("job", "search", "succeeded", "已给出 3 个可行方案。"), true);
  assert.deepEqual(h.calls.notify, []);
  assert.equal(h.calls.beep, 1);
  assert.equal(h.titles[0], "待查看 · 优化完成");
  h.advance(8000);
  assert.equal(h.titles.at(-1), PAGE);
});

test("a granted secure page uses the system notification", () => {
  const h = harness({ secure: true, permission: "granted" });
  h.alert.finish("job", "search", "failed", "场景数据缺失");
  assert.deepEqual(h.calls.notify, [["优化失败", "场景数据缺失"]]);
  assert.equal(h.calls.beep, 0);
  assert.deepEqual(h.titles, []);
});

test("a system notification that throws falls back to the tab and sound", () => {
  const h = harness({
    secure: true,
    permission: "granted",
    host: { notify() { throw new Error("blocked"); } },
  });
  h.alert.finish("job", "refine", "cancelled", "这次局部优化已停止，原方案仍在。");
  assert.equal(h.calls.beep, 1);
  assert.equal(h.titles[0], "待查看 · 局部优化已取消");
});

test("denied or not-yet-granted permission stays on the page", () => {
  for (const permission of ["denied", "default", "unsupported"]) {
    const h = harness({ secure: true, permission });
    h.alert.finish("job", "search", "succeeded", "已给出 1 个可行方案。");
    assert.equal(h.calls.notify.length, 0, permission);
    assert.equal(h.calls.beep, 1, permission);
  }
});

test("the same job alerts once", () => {
  const h = harness();
  assert.equal(h.alert.finish("job", "search", "succeeded", "已给出 1 个可行方案。"), true);
  assert.equal(h.alert.finish("job", "search", "failed", "运行失败"), false);
  assert.equal(h.calls.beep, 1);
  h.alert.finish("other", "search", "cancelled", "这次优化已停止，没有新方案。");
  assert.equal(h.calls.beep, 2);
  assert.equal(h.titles.at(-1), "待查看 · 优化已取消");
});

test("priming unlocks sound and asks only on a secure page that has not chosen", async () => {
  const insecure = harness();
  insecure.alert.prime();
  assert.equal(insecure.calls.arm, 1);
  assert.equal(insecure.calls.request, 0);

  const waiting = harness({ secure: true, permission: "default" });
  waiting.alert.prime();
  assert.equal(waiting.calls.arm, 1);
  assert.equal(waiting.calls.request, 1);

  const denied = harness({ secure: true, permission: "denied" });
  denied.alert.prime();
  assert.equal(denied.calls.request, 0);
  assert.equal(denied.calls.arm, 1);
});

test("unavailable audio and rejected permission cannot interrupt an optimization", async () => {
  const h = harness({secure: true, permission: "default", host: {
    arm() { throw new Error("AudioContext unavailable"); },
    requestPermission: async () => { throw new Error("permission unavailable"); },
  }});
  assert.doesNotThrow(() => h.alert.prime());
  await new Promise(resolve => setImmediate(resolve));
});

test("an audio failure keeps the visible reminder and never changes task success", () => {
  const h = harness({host: {beep() { throw new Error("audio unavailable"); }}});
  assert.doesNotThrow(() => h.alert.finish("job", "search", "succeeded", "已给出方案。"));
  assert.equal(h.titles[0], "待查看 · 优化完成");
  assert.equal(h.alert.finish("job", "search", "failed", "运行失败"), false);
});
