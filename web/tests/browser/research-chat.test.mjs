import assert from "node:assert/strict";
import test from "node:test";
import { chromium } from "playwright";
import { createServer } from "vite";

test("a question sent from the canvas opens its chat thread", async t => {
  const server = await createServer({server:{host:"127.0.0.1",port:0},logLevel:"error"});
  t.after(() => server.close());
  await server.listen();
  const browser = await chromium.launch();
  t.after(() => browser.close());
  const page = await browser.newPage({viewport:{width:1109,height:851}});
  page.setDefaultTimeout(5000);
  const thread = {id:"frame",kind:"research",title:"Research: studio",task:true,status:"idle"};
  const conversation = {id:"next",frame_id:"frame",harness:"codex",model:"sample",effort:"medium",repo:"studio",parent_id:"",quote:""};
  const body = {question:"Where are the examples?",harness:"codex",model:"sample",effort:"medium"};
  const notes = Array.from({length:24}, (_, i) => `Finding ${i + 1}: sample observation.`).join("\n");
  const files = ["research-plan.md", "prior-results.csv"].map((name, i) => ({
    id: String(i), name, mime:"text/plain", origin:"upload", size:32, url:`/api/files/${i}`,
  }));
  const data = {
    "/api/session": {me:"member",people:[],agent:{mark:"house"}},
    "/api/channels":[{id:"sample",name:"sample"}], "/api/catalog":{capabilities:[],templates:[]},
    "/api/channels/sample/messages":{roots:[],threads:{},replies:{}},
    "/api/channels/sample/canvas":[{thread,material:{text:"",files:[]},assets:[],boards:[],files:[],work:[],
      research:{...conversation,repo:{name:"studio",path:"studio",branch:"main"},repos:["studio","team/api"],files,source_notes:notes,conversations:[],notes:[]}}],
    "/api/research":{provider_api:true,models:{codex:[{id:"sample",name:"Sample",efforts:["medium"]}]},
      harnesses:[{id:"codex",title:"Codex",ready:true}],repos:[]},
    "/api/research/frame/conversations":conversation,
    "/api/threads/next":{thread:{id:"next",title:body.question,task:false},conversation,messages:[],boards:[],work:[]},
    "/api/brands":{brands:[],reading:[]}, "/api/production":{agents:[],episodes:[],jobs:[]},
  };
  await page.route("**/api/**", route => route.fulfill({json:data[new URL(route.request().url()).pathname] ?? {}}));
  await page.route("**/api/stream", () => {});
  await page.goto(new URL("c/sample/canvas/frame/research", server.resolvedUrls.local[0]).href);
  const card = page.getByRole("article",{name:"Research chat"});
  await card.getByRole("heading",{name:"Repositories"}).waitFor();
  await card.getByText("api",{exact:true}).waitFor();
  await card.getByRole("heading",{name:"Attached files"}).waitFor();
  for (const file of files) await card.getByRole("button",{name:file.name}).waitFor();
  await card.getByRole("heading",{name:"Notes and prior research"}).waitFor();
  const note = card.getByRole("region", {name:"Notes and prior research"});
  assert.equal(await note.innerText(),notes);
  await note.hover();
  await page.mouse.wheel(0,400);
  await page.waitForFunction(el => el.scrollTop > 0, await note.elementHandle());
  await card.getByRole("button",{name:"Research settings"}).click();
  await card.getByRole("combobox",{name:/Effort/}).waitFor();
  await card.getByRole("button",{name:"Research settings"}).click();
  const input = card.getByRole("textbox",{name:"Ask a question"});
  await input.fill(body.question);
  const request = page.waitForRequest(req => req.method() === "POST" && req.url().endsWith("/frame/conversations"));
  await card.getByRole("button",{name:"Send question"}).click();
  assert.deepEqual((await request).postDataJSON(),body);
  await page.getByRole("complementary",{name:"Thread"}).getByRole("heading",{name:body.question}).waitFor();
});
