import assert from "node:assert/strict";
import test from "node:test";
import { chromium } from "playwright";
import { createServer } from "vite";

test("new episodes submit the chosen narration and respect host availability", async (t) => {
  const server = await createServer({ server: { host: "127.0.0.1", port: 0 }, logLevel: "error" });
  t.after(() => server.close());
  await server.listen();
  const browser = await chromium.launch();
  t.after(() => browser.close());
  const page = await browser.newPage();
  page.setDefaultTimeout(5000);
  let available = true;
  let writerReady = true;
  await page.addInitScript(() => localStorage.setItem("episode-writer", "demo"));
  await page.route("**/api/episodes/options", route => route.fulfill({json: {
    seconds: {usual: [300, 420], least: 240, most: 600, gap: 30}, themes: [],
    writers: [{ id: "demo", ready: true, title: "HTTP caching sample" }, { id: "codex", ready: writerReady, title: "Codex" }],
    local_narrator: available, narrator: { ready: available },
  }}));
  await page.route("**/api/channels/test/episodes", route => route.fulfill({json: {id: "sample"}}));
  const picker = page.getByRole("combobox", { name: /Narration voice/ });
  const submit = async expected => {
    await page.getByRole("textbox", {name: "Notes"}).fill("Plant a herb garden.");
    const request = page.waitForRequest("**/api/channels/test/episodes");
    await page.getByRole("button", { name: "Plan the episode" }).click();
    const sent = (await request).postDataJSON();
    assert.equal(sent.settings.voice, expected);
    assert.equal(sent.settings.writer, "codex");
    assert.equal(sent.text, "Plant a herb garden.");
  };
  await page.goto(new URL("tests/browser/new-episode.html", server.resolvedUrls.local[0]).href);
  await page.getByRole("combobox", {name: /Local narrator/}).waitFor();
  await submit("local");
  await picker.click();
  await page.getByRole("option", {name: /ElevenLabs/}).click();
  await submit("narrator");
  available = false;
  await page.reload();
  await page.getByRole("combobox", {name: /Your recordings/}).waitFor();
  await picker.click();
  assert.ok(await page.getByRole("option", {name: /Local narrator/}).isDisabled());
  assert.ok(await page.getByRole("option", {name: /ElevenLabs/}).isDisabled());
  await page.keyboard.press("Escape");
  await submit("live");

  writerReady = false;
  await page.reload();
  await page.getByRole("textbox", {name: "Notes"}).fill("Different source notes.");
  const writer = page.getByRole("combobox", {name: /Episode writer/});
  await writer.click();
  assert.ok(await page.getByRole("option", {name: "Codex"}).isDisabled());
  assert.ok(await page.getByRole("button", {name: "Plan the episode"}).isDisabled());
  await page.getByRole("option", {name: "HTTP caching sample"}).click();
  await page.getByText(/Your notes are ignored/).waitFor();
  assert.ok(await page.getByRole("button", {name: "Plan HTTP caching sample"}).isEnabled());
});
