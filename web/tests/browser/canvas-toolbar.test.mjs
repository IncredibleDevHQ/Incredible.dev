import assert from "node:assert/strict";
import test from "node:test";
import { chromium } from "playwright";
import { createServer } from "vite";

test("canvas actions stay in the exposed canvas beside an open thread", async t => {
  const server = await createServer({server:{host:"127.0.0.1", port:0}, logLevel:"error"});
  t.after(() => server.close());
  await server.listen();
  const browser = await chromium.launch();
  t.after(() => browser.close());
  const page = await browser.newPage({viewport:{width:843,height:851}});
  page.setDefaultTimeout(5000);
  const thread = {id:"frame", title:"Sample project", task:false, kind:"chat", status:"done"};
  const data = {
    "/api/session": {me:"member", people:[], agent:{mark:"house"}},
    "/api/catalog": {capabilities:[],templates:[]}, "/api/research": {harnesses:[],models:{},repos:[]},
    "/api/channels": [{id:"sample", name:"sample"}],
    "/api/channels/sample/messages": {roots:[], threads:{}, replies:{}},
    "/api/channels/sample/canvas": [{thread, material:{text:"Sample", files:[]}, assets:[], boards:[], files:[], work:[]}],
    "/api/threads/frame": {thread, messages:[], boards:[], work:[]},
    "/api/brands": {brands:[],reading:[]}, "/api/production": {agents:[],episodes:[],jobs:[]},
  };
  await page.route("**/api/**", route => route.fulfill({json:data[new URL(route.request().url()).pathname] ?? {}}));
  // Keep the fixture’s event stream open while the thread is on screen.
  await page.route("**/api/stream", () => {});
  await page.goto(new URL("c/sample/canvas?thread=frame", server.resolvedUrls.local[0]).href);
  const panel = page.getByRole("complementary",{name:"Thread"});
  const close = panel.getByRole("button",{name:"Close thread"});
  await close.waitFor();
  const bar = page.locator(".canvas-bar");
  for (const width of [843, 780, 1024, 1440]) {
    await page.setViewportSize({width,height:851});
    const toolbar = await bar.boundingBox();
    const chat = await panel.boundingBox();
    assert.ok(toolbar && chat && toolbar.x + toolbar.width <= chat.x, `toolbar overlaps chat at ${width}px`);
    for (const name of ["Research","Templates","Episode"]) {
      await bar.getByRole("button",{name,exact:true}).click({trial:true});
    }
  }
  await page.setViewportSize({width:390,height:851});
  assert.equal(await bar.isVisible(),false);
  await close.click();
  await bar.getByRole("button",{name:"Research",exact:true}).click();
  await page.getByRole("dialog",{name:"Research a repository"}).waitFor();
});
