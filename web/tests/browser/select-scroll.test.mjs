import assert from "node:assert/strict";
import test from "node:test";
import { chromium } from "playwright";
import { createServer } from "vite";

test("scrolling a long Select keeps its position and keyboard navigation still reveals options", async (t) => {
  const server = await createServer({ server: { host: "127.0.0.1", port: 0 }, logLevel: "error" });
  t.after(() => server.close());
  await server.listen();
  const browser = await chromium.launch();
  t.after(() => browser.close());
  const page = await browser.newPage();
  await page.goto(new URL("tests/browser/select.html", server.resolvedUrls.local[0]).href);
  const field = page.getByRole("combobox");
  const list = page.getByRole("listbox");
  await field.click();
  await list.waitFor();

  // The scrollbar and touch scrolling can move the list without moving the active option.
  const settledOffset = (el) => new Promise(resolve => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve(el.scrollTop)));
  });
  await list.evaluate(el => { el.scrollTop = 200; });
  assert.equal(await list.evaluate(settledOffset), 200);
  await field.press("End");
  const bottom = await list.evaluate(el => el.scrollHeight - el.clientHeight);
  assert.ok(await list.evaluate(settledOffset) >= bottom - 6);
  await field.press("ArrowUp");
  await field.press("Enter");
  assert.match(await field.innerText(), /Component 27/);
  await field.click();
  assert.ok(await list.evaluate(settledOffset) > 0);
  await field.press("Home");
  assert.ok(await list.evaluate(settledOffset) <= 6);
  await field.press("Escape");
  assert.equal(await field.getAttribute("aria-expanded"), "false");
});
