import assert from "node:assert/strict";
import test from "node:test";
import { chromium } from "playwright";
import { createServer } from "vite";

test("old member links, activity controls and chart modes work across screen sizes", async t => {
  const server = await createServer({server:{host:"127.0.0.1",port:0},logLevel:"error"});
  t.after(() => server.close());
  await server.listen();
  const browser = await chromium.launch();
  t.after(() => browser.close());
  const page = await browser.newPage({viewport:{width:1319,height:766}});
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  const counts = {calls:1, input_tokens:100, output_tokens:10, usd:0.04, unpriced:0};
  const fixtures = {
    "/api/session":{me:"owner",authenticated:true,people:[],agent:{mark:"house"}},
    "/api/team":{owner:"owner@example.com",project:"owner",personal_url:"/",can_manage:true,incoming:[],members:[]},
    "/api/organization":{name:"Studio",description:"",website:""},
    "/api/channels":[],
    "/api/preferences/model":{options:[]},
    "/api/auth/session":{user:{has_password:true}},
    "/api/activity":{events:[],actors:[{actor:"owner",email:"owner@example.com"}],more:false},
    "/api/usage/report":{totals:counts, models:[], series:[0,1,2].map((day) => ({
      ...counts, at:1700000000 + day * 86400, input_tokens:(day + 1) * 100,
    }))},
  };
  await page.route("**/api/**", route => route.fulfill({json:fixtures[new URL(route.request().url()).pathname] ?? {}}));
  // Leave the live event stream pending while the test drives the REST-backed settings.
  await page.route("**/api/stream", () => {});
  await page.goto(new URL("settings", server.resolvedUrls.local[0]).href);
  await page.getByRole("heading",{name:"Profile settings"}).waitFor();
  await page.waitForURL("**/settings/profile");
  await page.getByRole("link",{name:"Preferences"}).click();
  await page.waitForURL("**/settings/preferences");
  await page.reload();
  await page.getByRole("heading",{name:"Preferences",exact:true}).waitFor();
  await page.goBack();
  await page.getByRole("heading",{name:"Profile settings"}).waitFor();
  await page.goto(new URL("settings/members", server.resolvedUrls.local[0]).href);
  await page.waitForURL("**/settings/organization");
  await page.getByRole("button",{name:"Invite member"}).click();
  await page.getByRole("dialog",{name:"Invite member"}).waitFor();
  await page.keyboard.press("Escape");
  await page.getByRole("link",{name:"Logs",exact:true}).click();
  const filter = page.getByRole("combobox",{name:/Performed by/});
  const refresh = page.getByRole("button",{name:"Refresh activity"});
  await filter.waitFor();
  const filterBox = await filter.boundingBox();
  const refreshBox = await refresh.boundingBox();
  assert.ok(filterBox.x + filterBox.width <= refreshBox.x);
  assert.ok(Math.abs(filterBox.y - refreshBox.y) < 2);
  await filter.click();
  await page.getByRole("option",{name:"owner@example.com"}).click();
  const request = page.waitForRequest(r => new URL(r.url()).searchParams.get("actor_id") === "owner");
  await refresh.click();
  await request;
  await page.getByRole("link",{name:"Usage",exact:true}).click();
  const canvas = page.getByRole("img",{name:/Tokens by day/});
  await canvas.waitFor();
  const capture = () => canvas.evaluate(el => el.toDataURL());
  const bars = await capture();
  await page.getByRole("button",{name:"Line chart"}).click();
  await page.waitForFunction(previous => document.querySelector(".usage-chart canvas").toDataURL() !== previous,bars);
  await page.getByRole("button",{name:"Cost",exact:true}).click();
  await page.getByRole("img",{name:/Cost by day.*line/}).waitFor();
  await page.getByRole("button",{name:"Today",exact:true}).click();
  await page.getByRole("img",{name:/Cost by hour.*line/}).waitFor();
  await page.setViewportSize({width:390,height:844});
  await page.getByRole("button",{name:"Bar chart"}).click();
  await page.getByRole("img",{name:/Cost by hour.*bar/}).waitFor();
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  assert.deepEqual(errors,[]);
});
