import assert from "node:assert/strict";
import test from "node:test";
import { chromium } from "playwright";
import { createServer } from "vite";

test("the trail says what a turn is at between two steps, and when it has gone silent", async t => {
  const server = await createServer({server:{host:"127.0.0.1",port:0},logLevel:"error"});
  t.after(() => server.close());
  await server.listen();
  const browser = await chromium.launch();
  t.after(() => browser.close());
  const page = await browser.newPage();
  page.setDefaultTimeout(4000);
  const url = new URL("tests/browser/trail.html",server.resolvedUrls.local[0]);
  const now = () => page.locator('.ag-sub[data-kind="now"]');
  const mark = () => page.locator('.ag-step[data-state="running"]');

  // thinking: the words of the thought as they come, and a stretch of thinking that ended
  await page.goto(url.href+"?thinking");
  await now().getByText(/^Thinking/).waitFor();
  assert.equal(await now().getAttribute("data-now"),"thinking");
  const first = await now().locator(".ag-thought").textContent();
  await page.waitForFunction(was => document.querySelector(".ag-thought")?.textContent !== was, first);
  assert.equal(await mark().getAttribute("data-signal"),"live");
  await page.getByText("Thought for 5m 35s").waitFor();
  // the newest step is no longer the one at work
  assert.equal(await page.locator(".ag-sub[data-latest]").count(),0);

  // an agent that gives no words for its thinking says how much so far
  await page.goto(url.href+"?tokens");
  await now().getByText("about 96,400 tokens so far").waitFor();

  // a file being written, and how much of it
  await page.goto(url.href+"?writing");
  await now().getByText("Writing",{exact:true}).waitFor();
  assert.match(await now().locator(".ag-sub-detail").textContent(),/pic-c4-b2-f1\.html · 1\d,\d{3} characters/);

  // silent for a while: the model has not answered yet, or the agent says nothing while it thinks
  await page.goto(url.href+"?waiting");
  await now().getByText(/^Waiting for the model/).waitFor();
  assert.equal(await mark().getAttribute("data-signal"),"quiet");
  await page.goto(url.href+"?quiet");
  await now().getByText(/^Quiet for 4m/).waitFor();
  await now().getByText("Kimi Code reports each step once it is done, and nothing while it thinks.").waitFor();
  assert.equal(await page.getByRole("button",{name:"Stop it"}).count(),0);

  // silent too long: it says so, and stops from there
  await page.goto(url.href+"?lost");
  await now().getByText(/^No sign of life for 2m/).waitFor();
  assert.equal(await mark().getAttribute("data-signal"),"lost");
  await now().getByText("Claude Code is usually heard from every few seconds, so it may be stuck.").waitFor();
  await page.getByRole("button",{name:"Stop it"}).click();
  await page.locator("#stopped").waitFor();
  await page.goto(url.href+"?lost-silent");
  await now().getByText(/^No sign of life for 12m/).waitFor();
  await now().getByText("That is longer than a step usually takes Kimi Code, so it may be stuck.").waitFor();

  // a page that has lost the house says so, still, and blames no agent for the silence
  await page.goto(url.href+"?cut");
  await now().getByText(/^Out of touch with the house 1m/).waitFor();
  assert.equal(await mark().getAttribute("data-signal"),"cut");
  assert.equal(await page.getByRole("button",{name:"Stop it"}).count(),0);
  assert.equal(await page.getByText(/No sign of life/).count(),0);

  // a finished stage keeps its work folded behind how many steps it took; opened, nothing moves
  await page.goto(url.href+"?kept");
  const fold = page.getByRole("button",{name:"3 steps"});
  await fold.waitFor();
  assert.equal(await page.locator(".ag-sub").count(),0);
  await fold.click();
  await page.getByText("Thought for 5m 35s").waitFor();
  assert.equal(await page.locator(".ag-branch[data-kept] .ag-sub").count(),4);
  assert.equal(await page.locator(".ag-light, .ag-branch[data-live], .ag-sub[data-latest]").count(),0);
  assert.equal(await fold.getAttribute("aria-expanded"),"true");
});
