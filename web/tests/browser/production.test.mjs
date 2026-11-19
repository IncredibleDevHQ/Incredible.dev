import assert from "node:assert/strict";
import test from "node:test";
import { chromium } from "playwright";
import { createServer } from "vite";

test("the production board hands jobs to agents, says what waits on the person, and narrows by episode", async t => {
  const server = await createServer({server:{host:"127.0.0.1",port:0},logLevel:"error"});
  t.after(() => server.close());
  await server.listen();
  const browser = await chromium.launch();
  t.after(() => browser.close());
  const page = await browser.newPage({viewport:{width:1600,height:900}});
  page.setDefaultTimeout(4000);
  const url = new URL("tests/browser/production.html",server.resolvedUrls.local[0]);
  await page.goto(url.href);
  const lane = name => page.getByRole("region",{name:new RegExp(`^${name}`)});
  const count = async name => Number(await lane(name).locator(".pb-lane-head .pb-count").textContent());
  const asked = () => page.evaluate(() => window.asked);

  // every job stands in the lane of who has to act on it
  await lane("To make").getByText("Diagram · Beats 2–5").first().waitFor();
  assert.deepEqual([await count("To make"),await count("Agents"),await count("Needs you"),await count("Done")],[5,5,3,2]);
  // what is to make is grouped by episode, then chapter
  assert.deepEqual(await lane("To make").locator('.pb-group-head[data-level="episode"] b').allTextContents(),["HTTP caching, explained","Shipping a fix past the cache"]);
  // an agent's row says how busy it is; one that is not set up here takes nothing
  const claude = page.locator('[data-agent="claude"]');
  await claude.getByText("2 running · 2 waiting").waitFor();
  assert.equal(await page.locator('[data-agent="kimi"]').getAttribute("data-ready"),null);
  // a running job says what its model is at, as its agent's own stream says it
  await claude.getByText(/^Thinking/).waitFor();
  await page.locator('[data-agent="codex"]').getByText(/^Quiet|^Drawing/).first().waitFor();
  // between two turns the house does the work: what the last turn said is over, however late it is told
  await page.evaluate(() => window.board.setState({pulses:{"ep_a:picture:c4.b9.f1":{at:Date.now()/1000,since:Date.now()/1000-30,doing:"thinking",text:"Still at it",amount:0}}}));
  const rendering = claude.locator(".pb-card",{hasText:"List · Beat 9"});
  await rendering.getByText(/^Rendering/).waitFor();
  assert.equal(await rendering.getByText(/Thinking/).count(),0);

  // carried over an agent, a job says what handing it over comes to; let go there, it is handed over
  const chips = lane("To make").getByRole("button",{name:/Chips · Beat 6/});
  const from = await chips.boundingBox();
  const to = await claude.locator(".pb-agent-head").boundingBox();
  await page.mouse.move(from.x+40,from.y+12);
  await page.mouse.down();
  await page.mouse.move(from.x+80,from.y+30,{steps:3});
  await page.mouse.move(to.x+60,to.y+10,{steps:6});
  await claude.getByText("+1 picture · about 10 min").waitFor();
  assert.equal(await claude.getAttribute("data-over"),"true");
  await page.mouse.up();
  await page.getByText("1 picture handed to Claude Code.").waitFor({state:"attached"});
  assert.deepEqual((await asked())[0].body,{jobs:[{episode:"ep_a",unit:"c2.b6.f1"}],agent:"claude",model:"",effort:"",start:true});
  assert.deepEqual([await count("To make"),await count("Agents")],[4,6]);
  // the carry was not also a press on the card
  assert.equal(await page.locator(".pb-card[data-open]").count(),0);

  // a whole chapter goes to the second agent with its number key, on what that agent's row picks
  await lane("To make").getByRole("button",{name:/^Chapter 4/}).focus();
  await page.keyboard.press("2");
  await page.getByText("2 pictures handed to Codex.").waitFor({state:"attached"});
  assert.deepEqual((await asked())[1].body.jobs.map(j => j.unit),["c4.b2.f1","c4.b7.f1"]);
  assert.equal((await asked())[1].body.agent,"codex");

  // a job unfolds in place: what it shows, and the way to start it with an agent
  const diagram = lane("To make").getByRole("button",{name:/Diagram · Beats 2–5/});
  await diagram.click();
  const open = page.locator(".pb-card[data-open]");
  await open.getByText(/its cache box in the middle/).waitFor();
  await open.getByRole("button",{name:"Start"}).click();
  await page.getByText("1 picture handed to Claude Code.").waitFor({state:"attached"});
  assert.deepEqual((await asked())[2].body.jobs,[{episode:"ep_a",unit:"c2.b2.f1"}]);

  // what waits on the person says why, and what stopped can be tried again
  const needs = lane("Needs you");
  await needs.getByText(/^Waiting for your go/).waitFor();
  await needs.getByText("Its plan is ready to read",{exact:false}).waitFor();
  await needs.getByText("Codex stopped: the plan's limit was reached.").click();
  await page.locator(".pb-card[data-open]").getByRole("button",{name:"Try again"}).waitFor();
  // its place in the episode's own page is a link
  assert.equal(await page.locator(".pb-card[data-open] .pb-link").getAttribute("href"),"/c/brand/episode/ep_b?at=c1&line=c1.b6.f1");
  // Escape folds it away and gives the card the focus back
  await page.keyboard.press("Escape");
  assert.equal(await page.locator(".pb-card[data-open]").count(),0);

  // a model picked on an agent's row goes with what is handed to it; unpicked, a job keeps its own
  await claude.getByRole("combobox",{name:/^Model for what is handed to Claude Code/}).click();
  await page.getByRole("option",{name:"Sonnet 5.5"}).click();
  await lane("To make").getByRole("button",{name:/^Shipping a fix past the cache/}).focus();
  await page.keyboard.press("1");
  await page.getByText("1 picture handed to Claude Code.").waitFor({state:"attached"});
  const last = (await asked()).at(-1).body;
  assert.deepEqual([last.jobs.map(j => j.unit),last.agent,last.model,last.effort],[["c1.b2.f1"],"claude","claude-sonnet-5-5",""]);

  // narrowed to one episode, the other's jobs are gone from every lane
  await page.evaluate(() => window.board.getState().setBoard({episode:"ep_b"}));
  await lane("Done").getByText("Diagram · Beat 1").waitFor();
  assert.equal(await count("Done"),1);
  assert.equal(await lane("Needs you").getByText(/^Waiting for your go/).count(),0);

  // no episodes: the board says where they come from
  await page.goto(url.href+"?empty");
  await page.getByText(/No episodes yet/).waitFor();
});
