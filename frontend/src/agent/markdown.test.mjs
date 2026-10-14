import assert from "node:assert/strict";
import { safeMarkdownUrl } from "../../.tmp-problem-snapshot/agent/markdown.js";

assert.equal(safeMarkdownUrl("https://example.com/a?q=1"), "https://example.com/a?q=1");
assert.equal(safeMarkdownUrl("http://example.com"), "http://example.com");
assert.equal(safeMarkdownUrl("mailto:user@example.com"), "mailto:user@example.com");
assert.equal(safeMarkdownUrl("/docs/agent"), "/docs/agent");
assert.equal(safeMarkdownUrl("#result"), "#result");
assert.equal(safeMarkdownUrl("javascript:alert(1)"), "");
assert.equal(safeMarkdownUrl("data:text/html,<script>alert(1)</script>"), "");
assert.equal(safeMarkdownUrl("vbscript:msgbox(1)"), "");
assert.equal(safeMarkdownUrl("**第 1"), "");

console.log("agent markdown URL assertions passed");
