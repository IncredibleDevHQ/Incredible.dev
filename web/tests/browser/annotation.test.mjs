import assert from "node:assert/strict";
import test from "node:test";
import { chromium } from "playwright";
import { createServer } from "vite";

test("inspecting a nested menu preserves it and its scroll position until a Studio interaction dismisses it", async (t) => {
  const server = await createServer({ server: { host: "127.0.0.1", port: 0 }, logLevel: "error" });
  t.after(() => server.close());
  await server.listen();
  const browser = await chromium.launch();
  t.after(() => browser.close());
  const page = await browser.newPage();
  await page.goto(new URL("tests/browser/annotation.html", server.resolvedUrls.local[0]).href);
  const trigger = page.getByRole("button", {name: "Settings", exact: true});
  const picker = page.getByRole("combobox");
  const list = page.getByRole("listbox");
  const inspector = page.getByRole("button", {name: "Annotation toolbar"});
  const outside = page.getByRole("button", {name: "Outside in Studio"});
  await trigger.click();
  await picker.click();
  await picker.press("End");
  const scroll = await list.evaluate(el => el.scrollTop);
  assert.ok(scroll > 0);
  // Page inspection may consume a press on a Studio element before its own handlers run.
  await outside.evaluate(el => {
    el.addEventListener("pointerdown", event => event.stopPropagation(), {once: true});
    el.dispatchEvent(new PointerEvent("pointerdown", {bubbles: true}));
  });
  assert.ok(await list.isVisible());
  await inspector.click();
  await inspector.press("Escape");
  assert.ok(await list.isVisible());
  assert.equal(await list.evaluate(el => el.scrollTop), scroll);
  await page.getByRole("option", {name: "Option 23", exact: true}).click();
  assert.match(await picker.innerText(), /Option 23/);
  await picker.click();
  await picker.press("Escape");
  assert.equal(await list.count(), 0);
  assert.ok(await picker.isVisible());
  await picker.press("Escape");
  assert.equal(await picker.count(), 0);
  await trigger.click();
  await picker.click();
  await outside.click();
  assert.equal(await list.count(), 0);
  assert.equal(await picker.count(), 0);
});
