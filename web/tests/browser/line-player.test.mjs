import assert from "node:assert/strict";
import test from "node:test";
import { chromium } from "playwright";
import { createServer } from "vite";

test("an unrecorded line keeps its chapter artwork during playback and seeking", async (t) => {
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
  assert.equal(await cover.isVisible(), true);
  await page.getByRole("button", { name: "Pause line" }).click();
  const seek = page.getByRole("slider", { name: "Seek within line" });
  await seek.press("End");
  assert.equal(await cover.isVisible(), true);
  await seek.press("Home");
  await cover.waitFor();
});

test("chapter controls keep chapter time, seek across beats while paused and replay from zero", async t => {
  const server = await createServer({ server: { host: "127.0.0.1", port: 0 }, logLevel: "error" });
  t.after(() => server.close());
  await server.listen();
  const browser = await chromium.launch();
  t.after(() => browser.close());
  const page = await browser.newPage();
  page.setDefaultTimeout(3000);
  await page.goto(new URL("tests/browser/line-player.html?chapter", server.resolvedUrls.local[0]).href);
  const player = page.getByRole("group", { name: "Chapter player" });
  await player.getByText("0:12 / 0:20").waitFor();
  const seek = player.getByRole("slider", {name: "Seek within chapter"});
  await seek.press("Home");
  assert.deepEqual(JSON.parse(await page.locator("#result").textContent()), {time: 0, play: false});
  await seek.press("End");
  await player.getByText("0:20 / 0:20").waitFor();
  await player.getByRole("button", {name: "Replay chapter"}).click();
  assert.deepEqual(JSON.parse(await page.locator("#result").textContent()), {time: 0, play: true});
});


test("the last beat can replay when the stored chapter duration rounds past its end", async t => {
  const server = await createServer({ server: { host: "127.0.0.1", port: 0 }, logLevel: "error" });
  t.after(() => server.close());
  await server.listen();
  const browser = await chromium.launch();
  t.after(() => browser.close());
  const page = await browser.newPage();
  await page.goto(new URL("tests/browser/line-player.html?rounded", server.resolvedUrls.local[0]).href);
  await page.getByRole("slider", {name: "Seek within chapter"}).press("End");
  assert.equal(await page.getByRole("button", {name: "Replay chapter"}).count(), 1);
});


test("an edited beat samples the original animation span in the stage", async t => {
  const server = await createServer({server:{host:"127.0.0.1",port:0},logLevel:"error"});
  t.after(() => server.close());
  await server.listen();
  const browser = await chromium.launch();
  t.after(() => browser.close());
  const page = await browser.newPage();
  await page.addInitScript(() => {
    Object.defineProperty(HTMLMediaElement.prototype, "readyState", {get:()=>2});
    Object.defineProperty(HTMLMediaElement.prototype, "duration", {get:()=>30});
    Object.defineProperty(HTMLMediaElement.prototype, "seeking", {get:()=>false});
    Object.defineProperty(HTMLMediaElement.prototype, "currentTime", {
      get(){return this.sampled ?? 0}, set(time){this.sampled = time},
    });
  });
  await page.goto(new URL("tests/browser/line-player.html?animation",server.resolvedUrls.local[0]).href);
  const video = page.locator(".ep-stage-pic video");
  await video.waitFor();
  await video.dispatchEvent("loadedmetadata");
  assert.equal(await video.evaluate(el=>el.currentTime),10);
});

test("video surface toggles playback without interfering with player controls", async t => {
  const server = await createServer({server:{host:"127.0.0.1",port:0},logLevel:"error"});
  t.after(() => server.close()); await server.listen();
  const browser = await chromium.launch(); t.after(() => browser.close());
  const page = await browser.newPage(); page.setDefaultTimeout(3000);
  await page.goto(new URL("tests/browser/line-player.html",server.resolvedUrls.local[0]).href);
  await page.getByRole("button",{name:"Play video",exact:true}).click();
  await page.getByRole("button",{name:"Pause line",exact:true}).waitFor();
  await page.getByRole("button",{name:"Pause video",exact:true}).click();
  await page.getByRole("button",{name:"Play line",exact:true}).waitFor();
  await page.getByRole("button",{name:"Play video",exact:true}).press("Space");
  await page.getByRole("button",{name:"Pause line",exact:true}).click();
  await page.getByRole("button",{name:"Play video",exact:true}).waitFor();
  await page.getByRole("button",{name:"Playback settings"}).click();
  await page.getByRole("button",{name:"Play line",exact:true}).waitFor();
});
