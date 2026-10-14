import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  KEY_PLACEHOLDER_EMPTY,
  KEY_PLACEHOLDER_SET,
  MEMORY_DISABLED_NOTE,
  MODEL_SAVED,
  SETTINGS_SECTION_ORDER,
  canSaveModel,
  configSourceLabel,
  keyPlaceholder,
} from "../../.tmp-problem-snapshot/agent/agent_settings_form.js";

assert.deepEqual(SETTINGS_SECTION_ORDER, ["模型 API 配置", "长期记忆"]);
assert.equal(canSaveModel(true), false);
assert.equal(canSaveModel(false), true);
assert.equal(keyPlaceholder(true), KEY_PLACEHOLDER_SET);
assert.equal(keyPlaceholder(false), KEY_PLACEHOLDER_EMPTY);
assert.equal(configSourceLabel("后端 .env"), "当前配置来源：后端 .env");
assert.equal(configSourceLabel("外部环境变量"), "当前配置来源：外部环境变量");
assert.equal(MODEL_SAVED, "模型配置已保存");
assert.equal(MEMORY_DISABLED_NOTE.includes("文字记忆已清除"), true);

const dialog = readFileSync(new URL("./agent_settings_dialog.tsx", import.meta.url), "utf8");
assert.equal(dialog.includes("清除已保存的 API Key"), false);
assert.equal(dialog.includes("管理员密码"), false);
assert.equal(dialog.includes("管理员验证"), false);
const model = dialog.indexOf("<strong>模型 API 配置</strong>");
const memory = dialog.indexOf("<strong>长期记忆</strong>");
assert.ok(model > 0 && model < memory);
assert.equal(dialog.includes("保存模型配置"), true);
assert.equal(dialog.includes("localStorage"), false);
assert.equal(dialog.includes("sessionStorage"), false);

const css = readFileSync(new URL("../styles.css", import.meta.url), "utf8");
const rule = css.slice(css.indexOf(".agent-settings-dialog input[type=\"text\"]"));
assert.equal(rule.includes("color: #e7fbff"), true);
assert.equal(rule.includes("background: rgb(8 28 40 / 90%)"), true);
assert.equal(rule.includes("border-color: #39f3ff"), true);
assert.equal(css.includes(".agent-settings-dialog input::placeholder"), true);
