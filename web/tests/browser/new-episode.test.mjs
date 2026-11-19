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
    generation_models: { codex: [{ id: "", name: "CLI default", efforts: [] }] },
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
  assert.ok(await page.getByRole("option", {name: /^ElevenLabs/}).isDisabled());
  assert.ok(await page.getByRole("option", {name: /Cloned voice/}).isDisabled());
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

test("new episodes can choose or record a channel clone before planning", async t => {
  const server = await createServer({server: {host: "127.0.0.1", port: 0}, logLevel: "error"});
  t.after(() => server.close());
  await server.listen();
  const browser = await chromium.launch({args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"]});
  t.after(() => browser.close());
  const page = await browser.newPage({permissions: ["microphone"]});
  page.setDefaultTimeout(5000);
  const saved = {id: "savedvoice01", name: "Saved narrator"};
  const created = {id: "createdvoice01", name: "New narrator"};
  const bodies = [];
  let clones = 0;
  await page.route("**/api/episodes/options", route => route.fulfill({json: {
    seconds: {usual: [300, 420], least: 240, most: 600, gap: 30}, themes: [],
    writers: [{id: "codex", ready: true, title: "Codex"}], generation_models: {},
    local_narrator: true, narrator: {ready: true},
  }}));
  await page.route("**/api/channels/test/voices", route => {
    if (route.request().method() === "GET") return route.fulfill({json: {voices: [saved]}});
    const form = route.request().postDataBuffer().toString("latin1");
    assert.match(form, /name="consent"\r\n\r\ntrue/);
    assert.match(form, /name="file"; filename="voice-sample\./);
    if (++clones === 1) return route.fulfill({status: 422, json: {detail: "Voice service unavailable"}});
    return route.fulfill({json: created});
  });
  await page.route("**/api/channels/test/episodes", route => {
    bodies.push(route.request().postDataJSON());
    return route.fulfill({json: {id: "sample"}});
  });

  await page.goto(new URL("tests/browser/new-episode.html", server.resolvedUrls.local[0]).href);
  const notes = page.getByRole("textbox", {name: "Notes"});
  await notes.fill("Plant a herb garden.");
  const narration = page.getByRole("combobox", {name: /Narration voice/});
  const voiceList = page.getByRole("combobox", {name: /Channel voices/});
  const plan = page.getByRole("button", {name: "Plan the episode"});
  const submit = async expected => {
    const request = page.waitForRequest("**/api/channels/test/episodes");
    await plan.click();
    assert.deepEqual((await request).postDataJSON().settings.narrator, expected);
  };
  assert.equal(await voiceList.count(), 0);
  await narration.click();
  await page.getByRole("option", {name: /Cloned voice/}).click();
  assert.equal(await plan.isEnabled(), false);
  await voiceList.click();
  await page.getByRole("option", {name: saved.name}).click();
  await submit(saved);
  await page.getByRole("button", {name: "Add cloned voice"}).click();
  const dialog = page.getByRole("dialog", {name: "Clone your voice"});
  await dialog.waitFor();
  await page.keyboard.press("Escape");
  await dialog.waitFor({state: "detached"});
  assert.equal(await notes.inputValue(), "Plant a herb garden.");
  await page.getByRole("button", {name: "Add cloned voice"}).click();
  await dialog.getByRole("textbox", {name: "Name"}).fill(created.name);
  await dialog.getByRole("button", {name: "Record sample"}).click();
  await dialog.getByText("Recording · 0:01", {exact: true}).waitFor();
  await dialog.getByRole("button", {name: "Stop recording"}).click();
  await dialog.getByLabel("Preview recording").waitFor();
  const create = dialog.getByRole("button", {name: "Clone and use voice"});
  assert.equal(await create.isEnabled(), false);
  await dialog.getByRole("checkbox").check();
  await create.click();
  await dialog.getByText("Voice service unavailable").waitFor();
  assert.equal(bodies.length, 1);
  await create.click();
  await dialog.waitFor({state: "detached"});
  await page.getByRole("combobox", {name: /Channel voices.*New narrator/}).waitFor();
  await submit(created);
  await narration.click();
  await page.getByRole("option", {name: /Local narrator/}).click();
  assert.equal(await voiceList.count(), 0);
  await submit(undefined);
  assert.equal(clones, 2);
});
