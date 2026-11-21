import assert from "node:assert/strict";
import test from "node:test";
import { chromium } from "playwright";
import { createServer } from "vite";

test("chapter and recording actions update the URL and reload restores the recorder", async (t) => {
  const server = await createServer({ server: { host: "127.0.0.1", port: 0 }, logLevel: "error" });
  t.after(() => server.close());
  await server.listen();
  const browser = await chromium.launch({
    args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"],
  });
  t.after(() => browser.close());
  const page = await browser.newPage();
  page.setDefaultTimeout(5000);
  const chapters = ["The first question", "The second question"].map((question, index) => {
    const id = `c${index + 1}`;
    const frame = {
      id: `${id}.b1.f1`, vo: question, layout: "full", presence: "person",
      start: 0, seconds: 4, words: 3,
    };
    return { id, question, seconds: 4, beats: [{ id: `${id}.b1`, frames: [frame] }] };
  });
  const view = {
    id: "ep_fixture", title: "Sample film", status: "studio", stage: {}, writer: "demo",
    approved: true, channel_id: "test", units: [], takes: [], runs: [], waiting: [], rerecord: [],
    checks: [], builders: {}, channel_voices: [], film_state: {}, clock: null,
    background: { color: "#fff", brand_color: "#fff", textures: {} },
    settings: { presenter: "on", voice: "live", writer: "demo", portrait: "mira" },
    options: {
      themes: [], writers: [], generation_models: {}, picture_writers: [], pictures: [],
      transitions: [], narrator: {}, geometry: { frame: [1920, 1080], layouts: { full: { person: [0, 0, 1920, 1080] } } },
    },
    plan: { brief: { idea: "Sample film" }, chapters, totals: { seconds: 8 } },
  };
  const data = {
    "/api/auth/session": {},
    "/api/session": { me: "you", people: [{ id: "you", name: "Fixture", initials: "F" }] },
    "/api/channels": [{ id: "test", name: "Studio" }],
    "/api/catalog": {},
    "/api/brands": { brands: [], reading: [] },
    "/api/production": { agents: [], episodes: [], jobs: [] },
    "/api/channels/test/messages": { roots: [], threads: {}, replies: {} },
    "/api/channels/test/canvas": [],
    "/api/episodes/ep_fixture": view,
  };
  await page.route("**/api/**", (route) => route.fulfill({
    json: data[new URL(route.request().url()).pathname] ?? {},
  }));

  const url = new URL("c/Studio/episode/ep_fixture", server.resolvedUrls.local[0]).href;
  await page.goto(url);
  const slides = page.getByRole("navigation", { name: "The film and its chapters" });
  const chapter = slides.getByRole("button", { name: /The second question/ });
  await chapter.click();
  await page.waitForURL(url + "?at=c2");
  await page.getByRole("button", { name: "Record chapter 2" }).click();
  await page.waitForURL(url + "?at=c2&record=1");
  await page.getByRole("button", { name: /Start recording/ }).waitFor();
  await page.reload();
  await page.getByRole("button", { name: /Start recording/ }).waitFor();
  assert.equal(await chapter.getAttribute("aria-current"), "true");
  await page.getByRole("button", { name: "Back to chapter" }).first().click();
  await page.waitForURL(url + "?at=c2");
  await slides.getByRole("button", { name: /The film/ }).click();
  await page.waitForURL(url);
  await page.goBack();
  await page.waitForURL(url + "?at=c2");
  assert.equal(await chapter.getAttribute("aria-current"), "true");
});
