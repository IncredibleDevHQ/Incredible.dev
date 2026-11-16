import assert from "node:assert/strict";
import test from "node:test";
import { chromium } from "playwright";
import { createServer } from "vite";

test("an unrecorded line opens with its chapter cover and reveals the frame during playback", async (t) => {
  const server = await createServer({ server: { host: "127.0.0.1", port: 0 }, logLevel: "error" });
  t.after(() => server.close());
  await server.listen();
  const browser = await chromium.launch();
  t.after(() => browser.close());
  const page = await browser.newPage();
  await page.goto(new URL("tests/browser/line-player.html", server.resolvedUrls.local[0]).href);

  const cover = page.getByText("Chapter artwork");
  await cover.waitFor();
  await page.getByRole("button", { name: "Play line" }).click();
  await page.getByRole("button", { name: "Pause line" }).waitFor();
  assert.equal(await cover.isVisible(), false);
  await page.getByRole("button", { name: "Pause line" }).click();
  const seek = page.getByRole("slider", { name: "Seek within line" });
  await seek.press("End");
  assert.equal(await cover.isVisible(), false);
  await seek.press("Home");
  await cover.waitFor();
});
