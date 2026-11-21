import assert from "node:assert/strict";
import test from "node:test";
import { chromium } from "playwright";
import { createServer } from "vite";

test("provider logos are centered with space before the selected value and each option", async t => {
  const server = await createServer({server:{host:"127.0.0.1",port:0},logLevel:"error"});
  t.after(() => server.close());
  await server.listen();
  const browser = await chromium.launch();
  t.after(() => browser.close());
  const page = await browser.newPage({viewport:{width:998,height:766}});
  const data = {
    "/api/session": {me:"you",authenticated:true,people:[],agent:{mark:"house"}},
    "/api/channels": [],
    "/api/preferences/model": {default:"openai:test", model:"", effort:"",options:[
      {id:"openai:test",provider:"openai",name:"Test model",efforts:["medium"]},
    ]},
  };
  await page.route("**/api/**", route => route.fulfill({json:data[new URL(route.request().url()).pathname] ?? {}}));
  await page.goto(new URL("settings", server.resolvedUrls.local[0]).href);
  const trigger = page.getByRole("combobox",{name:/Default provider/});
  async function assertAligned(row) {
    const { offset, gap } = await row.evaluate(element => {
      const icon = element.querySelector("img").getBoundingClientRect();
      const text = element.querySelector(".choice-text").getBoundingClientRect();
      return {offset:(icon.top + icon.bottom - text.top - text.bottom) / 2, gap:text.left - icon.right};
    });
    assert.ok(Math.abs(offset) <= 1, `logo center offset: ${offset}px`);
    assert.ok(gap >= 8, `logo-to-text gap: ${gap}px`);
  }
  await assertAligned(trigger);
  await trigger.click();
  const options = await page.getByRole("option").all();
  assert.equal(options.length,3);
  for (const row of options) await assertAligned(row);
  await page.keyboard.press("Escape");
  assert.equal(await trigger.getAttribute("aria-expanded"),"false");
});
