import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

test("readable labels may share a row but must not cover each other or leave the canvas", async t => {
  const browser = await chromium.launch();
  t.after(() => browser.close());
  const page = await browser.newPage();
  await page.setContent('<svg id="scene" width="320" height="200"><text x="10" y="40">Original records</text><text x="18" y="40">Index</text><text x="300" y="80">Off canvas</text><g opacity="0"><text x="10" y="40">Hidden</text></g></svg>');
  await page.addScriptTag({path:fileURLToPath(new URL("../../../src/design_agent/episode/check_labels.js",import.meta.url))});
  const check = () => page.evaluate(() => checkLabels(document.querySelector("svg")));
  const findings = await check();
  assert.ok(findings.some(f => f.includes("Original records") && f.includes("Index")));
  assert.ok(findings.some(f => f.includes("Off canvas")));
  assert.ok(findings.every(f => !f.includes("Hidden")));
  await page.locator("text").nth(1).evaluate(e => e.setAttribute("x",165));
  await page.locator("text").nth(2).evaluate(e => e.setAttribute("x",20));
  assert.deepEqual(await check(), []);
  await page.locator("svg").evaluate(svg => svg.insertAdjacentHTML("beforeend", '<rect x="2" y="15" width="140" height="40" fill="white" />'));
  assert.ok((await check()).some(f => f.includes("covered") && f.includes("Original records")));
});
