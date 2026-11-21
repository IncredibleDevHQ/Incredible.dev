import assert from "node:assert/strict";
import test from "node:test";
import { chromium } from "playwright";
import { createServer } from "vite";

test("record or upload, retry a conversion, and compare saved test clones after refresh", async t => {
  const server = await createServer({ server: { host: "127.0.0.1", port: 0 }, logLevel: "error" });
  t.after(() => server.close());
  await server.listen();
  const browser = await chromium.launch({
    args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"],
  });
  t.after(() => browser.close());
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const episode = "ep_demo123";
  const uploads = [];
  const clips = [];
  await page.route("**/api/**", route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/auth/session") return route.fulfill({ json: {} });
    if (path === `/api/episodes/${episode}/voice-tests`) {
      if (request.method() === "GET") return route.fulfill({json: {clips}});
      uploads.push(request.postDataBuffer());
      if (uploads.length === 1) return route.fulfill({status: 422, json: {detail: "Try again"}});
      const clip = {id: String(uploads.length), name: "Morning read", expires_at: Date.now()/1000+3600};
      clips.unshift(clip);
      return route.fulfill({json: clip});
    }
    if (/voice-tests\/\d+\/(original|clone)$/.test(path)) return route.fulfill({body: wav, contentType: "audio/wav"});
    return route.fulfill({status: 404});
  });
  const wav = Buffer.alloc(44 + 16000);
  wav.write("RIFF"); wav.writeUInt32LE(wav.length - 8, 4); wav.write("WAVEfmt ", 8);
  wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22);
  wav.writeUInt32LE(8000, 24); wav.writeUInt32LE(16000, 28);
  wav.writeUInt16LE(2, 32); wav.writeUInt16LE(16, 34);
  wav.write("data", 36); wav.writeUInt32LE(16000, 40);
  await page.route("**/fixture.wav", route => route.fulfill({ body: wav, contentType: "audio/wav" }));
  await page.goto(new URL(`c/demo/episode/${episode}/voice-test`, server.resolvedUrls.local[0]).href);
  await page.getByRole("heading", { name: "Voice test", exact: true }).waitFor({ timeout: 3000 });
  await page.getByRole("button", {name:"Upload audio"}).waitFor({timeout:2000});
  await page.getByText("Reading scripts", {exact:true}).click();
  await page.getByRole("button", {name:"Dinner for six"}).click();
  await page.getByText(/I thought cooking for six/).waitFor();
  await page.getByRole("button", {name:"Record audio", exact:true}).click();
  await page.getByRole("button", {name:/Stop recording · [1-9]/}).click();
  await page.getByLabel("Original audio playback").waitFor();
  await page.locator("input[type=file]").setInputFiles({name:"empty.wav", mimeType:"audio/wav", buffer:Buffer.alloc(0)});
  await page.getByRole("alert").waitFor();
  await page.locator("input[type=file]").setInputFiles({name:"Morning read.wav", mimeType:"audio/wav", buffer:wav});
  const create = page.getByRole("button", {name:"Create test clone", exact:true});
  assert.equal(await create.isEnabled(), false);
  await page.getByLabel("What should the clone say?").fill("Let's meet at the station.");
  await page.getByRole("checkbox").check();
  await create.click();
  await page.getByText("Try again", {exact:true}).waitFor();
  await create.click();
  await page.getByLabel("Cloned playback").evaluate(el => el.play());
  assert.equal(await page.getByLabel("Cloned playback").evaluate(el=>el.duration),1);
  await create.click();
  await page.getByRole("button", {name:/Morning read.*2/}).waitFor();
  await page.reload();
  await page.getByRole("button", {name:/Morning read.*1/}).click();
  await page.getByLabel("Source playback").evaluate(el => el.play());
  await page.getByLabel("Cloned playback").evaluate(el => el.play());
  await page.getByRole("button", {name:"Use this recording"}).click({timeout:1500});
  await page.getByLabel("What should the clone say?").waitFor();
  assert.equal(uploads.length,3);
  assert.ok(uploads.every(body=>body.includes(Buffer.from("Let's meet at the station."))));
  assert.ok(uploads.every(body=>body.includes(Buffer.from("RIFF"))));
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),true);
});
