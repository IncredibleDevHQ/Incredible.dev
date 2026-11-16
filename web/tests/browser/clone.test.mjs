import assert from "node:assert/strict";
import test from "node:test";
import { chromium } from "playwright";
import { createServer } from "vite";

test("voice setup records locally, requires consent, uploads the sample and dismisses on backdrop", async (t) => {
  const server = await createServer({ server: { host: "127.0.0.1", port: 0 }, logLevel: "error" });
  t.after(() => server.close());
  await server.listen();
  const browser = await chromium.launch({args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"]});
  t.after(() => browser.close());
  const page = await browser.newPage({ permissions: ["microphone"] });
  page.setDefaultTimeout(5000);
  await page.addInitScript(() => {
    const request = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    navigator.mediaDevices.getUserMedia = async constraints => {
      const stream = await request(constraints);
      window.testMicrophone = stream;
      return stream;
    };
  });
  const voiceRequests = [];
  await page.route("**/api/episodes/test-episode/voice", route => {
    voiceRequests.push(route.request().postDataBuffer());
    return route.fulfill({json: { id: "test-episode" }});
  });
  await page.goto(new URL("tests/browser/clone.html", server.resolvedUrls.local[0]).href);
  const dialog = page.getByRole("dialog");
  await dialog.waitFor();
  assert.equal(await dialog.getByRole("radiogroup").count(), 0);
  await page.mouse.click(2, 2);
  await dialog.waitFor({ state: "detached" });
  await page.getByRole("button", {name:"Open voice setup"}).click();
  const record = page.getByRole("button", {name:"Record sample"});
  await record.click();
  await page.getByText("Recording · 0:01", {exact:true}).waitFor();
  await page.getByRole("button", {name:"Stop recording"}).click();
  await page.getByLabel("Preview recording").waitFor();
  assert.equal(await page.evaluate(() => window.testMicrophone.getAudioTracks()[0].readyState), "ended");
  const submit = page.getByRole("button", {name:"Clone and use voice"});
  assert.equal(await submit.isEnabled(), false);
  assert.equal(voiceRequests.length, 0);
  await page.getByRole("checkbox").check();
  await submit.click();
  await dialog.waitFor({state:"detached"});
  assert.equal(voiceRequests.length, 1);
  assert.match(voiceRequests[0].toString("latin1"), /name="file"; filename="voice-sample\./);
  await page.getByRole("button", {name:"Open voice setup"}).click();
  await page.getByRole("button", {name:"Record sample"}).click();
  await page.getByRole("button", {name:"Stop recording"}).waitFor();
  await page.keyboard.press("Escape");
  await dialog.waitFor({state:"detached"});
  assert.equal(voiceRequests.length, 1);
  assert.equal(await page.evaluate(() => window.testMicrophone.getAudioTracks()[0].readyState), "ended");

  await page.getByRole("button", {name:"Open voice setup"}).click();
  await page.evaluate(() => {
    navigator.mediaDevices.getUserMedia = async () => { throw new DOMException("denied", "NotAllowedError"); };
  });
  await page.getByRole("button", {name:"Record sample"}).click();
  assert.match(await page.getByRole("alert").innerText(), /Microphone access was denied/);
  const upload = page.locator('input[type="file"]');
  await upload.setInputFiles({name:"empty.wav", mimeType:"audio/wav", buffer:Buffer.alloc(0)});
  assert.match(await page.getByRole("alert").innerText(), /empty/);
  assert.equal(await submit.isEnabled(), false);
  await upload.setInputFiles({name:"sample.wav", mimeType:"audio/wav", buffer:Buffer.from("sample")});
  await page.getByLabel("Preview recording").waitFor();
  assert.equal(await page.getByRole("alert").count(), 0);
  await page.keyboard.press("Escape");

  const picks = [];
  await page.route("**/api/episodes/test-episode/choices", route => {
    const body = route.request().postDataJSON();
    picks.push(body.settings);
    return route.fulfill({json: body});
  });
  await page.route("**/api/voices", route => route.fulfill({json: {voices: []}}));
  await page.goto(new URL("tests/browser/clone.html?saved", server.resolvedUrls.local[0]).href);
  await page.getByRole("button", {name:"Voice: Your voice"}).click();
  const saved = page.getByRole("radio", {name:/Cloned voice Sample narrator/});
  await saved.click();
  await page.getByRole("button", {name:"Voice: Sample narrator"}).waitFor();
  assert.ok(await saved.isChecked());
  assert.equal(picks[0].narrator.id, "stored-voice");
  await page.getByRole("radio", {name:/ElevenLabs Choose/}).click();
  await page.getByRole("button", {name:"Voice: ElevenLabs"}).waitFor();
  assert.equal(await saved.isChecked(), false);
  assert.equal(picks[1].narrator, null);
  assert.equal(voiceRequests.length, 1);
});
