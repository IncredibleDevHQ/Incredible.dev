import assert from "node:assert/strict";
import test from "node:test";
import { chromium } from "playwright";
import { createServer } from "vite";

test("chapter regeneration confirms scope and supports a one-run model choice", async t => {
  const server = await createServer({ server: { host: "127.0.0.1", port: 0 }, logLevel: "error" });
  t.after(() => server.close());
  await server.listen();
  const browser = await chromium.launch();
  t.after(() => browser.close());
  const page = await browser.newPage({ viewport: { width: 380, height: 640 } });
  page.setDefaultTimeout(3500);
  const endpoint = "**/api/episodes/fixture/chapters/chapter-2/regenerate";
  const submissions = [];
  await page.route(endpoint, route => {
    submissions.push(route.request().postDataJSON());
    return route.fulfill({ json: {} });
  });
  await page.goto(new URL("tests/browser/regenerate-chapter.html", server.resolvedUrls.local[0]).href);
  const trigger = page.getByRole("button", { name: "Regenerate chapter" });
  const dialog = page.getByRole("dialog", { name: "Regenerate chapter" });
  const confirm = dialog.getByRole("button", { name: "Regenerate 3 visuals" });
  const provider = dialog.getByRole("combobox", { name: /Provider/ });

  await trigger.click();
  await dialog.getByText(/existing chapter plan/).waitFor();
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await dialog.waitFor({ state: "hidden" });
  assert.equal(submissions.length, 0);

  await trigger.click();
  await Promise.all([page.waitForResponse(endpoint), confirm.click()]);
  await dialog.waitFor({ state: "hidden" });

  await trigger.click();
  await provider.click();
  assert.equal(await page.getByRole("option", { name: /Claude/ }).getAttribute("aria-disabled"), "true");
  await page.getByRole("option", { name: "Codex" }).click();
  await dialog.getByRole("combobox", { name: /Model/ }).click();
  await page.getByRole("option", { name: "Chosen model" }).click();
  await Promise.all([page.waitForResponse(endpoint), confirm.click()]);
  await dialog.waitFor({ state: "hidden" });
  assert.deepEqual(submissions, [{}, { provider: "codex", model: "chosen" }]);
});
