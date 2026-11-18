import assert from "node:assert/strict";
import test from "node:test";
import { chromium } from "playwright";
import { createServer } from "vite";

test("beat effort supports keyboard adjustment and resets for a fixed-effort model", async t => {
  const server = await createServer({ server: { host: "127.0.0.1", port: 0 }, logLevel: "error" });
  t.after(() => server.close());
  await server.listen();
  const browser = await chromium.launch();
  t.after(() => browser.close());
  const page = await browser.newPage();
  page.setDefaultTimeout(3500);
  const choices = "**/api/episodes/fixture/choices";
  await page.route(choices, route => route.fulfill({json: {}}));
  await page.goto(new URL("tests/browser/beat-picker.html", server.resolvedUrls.local[0]).href);
  const open = page.getByRole("button", {name: /Edit model/});
  await open.click();
  const effort = page.getByRole("slider", {name: "Effort"});
  assert.equal(await effort.getAttribute("aria-valuetext"), "Medium");
  await effort.press("Home");
  assert.equal(await effort.getAttribute("aria-valuetext"), "Default");
  await effort.press("ArrowRight");
  assert.equal(await effort.getAttribute("aria-valuetext"), "Low");
  const save = async () => {
    const request = page.waitForRequest(choices);
    await page.getByRole("button", {name: "Use for beat"}).click();
    return (await request).postDataJSON().units.beat;
  };
  assert.deepEqual(await save(), {builder:"codex", model:"adjustable", effort:"low"});
  await open.click();
  await page.getByRole("combobox", {name:/Model.*Adjustable/}).click();
  await page.getByRole("option", {name:"Fixed"}).click();
  assert.equal(await effort.count(), 0);
  assert.deepEqual(await save(), {builder:"codex", model:"fixed", effort:""});

  await page.goto(new URL("tests/browser/beat-picker.html?default", server.resolvedUrls.local[0]).href);
  await page.getByRole("button", {name: "Edit model: Codex · gpt-6.1-sol"}).click();
  await page.getByRole("combobox", {name: "Model Default · gpt-6.1-sol"}).click();
  await page.getByRole("option", {name: "Default · gpt-6.1-sol", exact: true}).waitFor();
  assert.equal(await page.getByRole("option", {name: "gpt-6.1-sol", exact: true}).count(), 0);
  await page.keyboard.press("Escape");
  assert.deepEqual(await save(), {builder:"codex", model:"", effort:""});
  await open.click();
  await effort.press("ArrowRight");
  assert.deepEqual(await save(), {builder:"codex", model:"", effort:"low"});

  await page.goto(new URL("tests/browser/beat-picker.html?pinned", server.resolvedUrls.local[0]).href);
  await page.getByRole("button", {name: "Edit model: Codex · gpt-6.1-sol · Low"}).click();
  assert.deepEqual(await save(), {builder:"codex", model:"gpt-6.1-sol", effort:"low"});
  await open.click();
  await page.getByRole("combobox", {name: "Model gpt-6.1-sol"}).click();
  await page.getByRole("option", {name: "Use default", exact: true}).click();
  assert.deepEqual(await save(), {builder:"codex", model:"", effort:""});
});
