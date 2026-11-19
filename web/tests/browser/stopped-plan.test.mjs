import assert from "node:assert/strict";
import test from "node:test";
import { chromium } from "playwright";
import { createServer } from "vite";

test("a stopped plan lets the user retry with a supported model", async t => {
  const server = await createServer({server: {host: "127.0.0.1", port: 0}, logLevel: "error"});
  t.after(() => server.close());
  await server.listen();
  const browser = await chromium.launch();
  t.after(() => browser.close());
  const page = await browser.newPage();
  const route = "**/api/episodes/test-episode/again";
  await page.route(route, request => request.fulfill({json: {}}));
  await page.goto(new URL("tests/browser/stopped-plan.html", server.resolvedUrls.local[0]).href);
  await page.getByRole("combobox", {name: "Model Default · gpt-5.6-sol"}).click();
  assert.equal(await page.getByRole("option", {name: "gpt-6.1-terra", exact: true}).count(), 0);
  await page.getByRole("option", {name: "gpt-5.6-terra", exact: true}).click();
  await page.getByRole("combobox", {name: "Effort Default"}).click();
  await page.getByRole("option", {name: "Medium", exact: true}).click();
  const submitted = page.waitForRequest(route);
  await page.getByRole("button", {name: "Pick it up"}).click();
  assert.deepEqual((await submitted).postDataJSON(), {writer: "", model: "gpt-5.6-terra", effort: "medium"});
});
