import assert from "node:assert/strict";
import test from "node:test";
import { chromium } from "playwright";
import { createServer } from "vite";

test("redraw review lists every stale visual by chapter and only submits on confirmation", async t => {
  const server = await createServer({server:{host:"127.0.0.1",port:0},logLevel:"error"});
  t.after(() => server.close());
  await server.listen();
  const browser = await chromium.launch();
  t.after(() => browser.close());
  const page = await browser.newPage();
  page.setDefaultTimeout(3000);
  let applies = 0;
  await page.route("**/api/episodes/fixture/apply", route => { applies++; return route.fulfill({json:{}}); });
  const url = new URL("tests/browser/redraw.html",server.resolvedUrls.local[0]);
  await page.goto(url.href);
  const open = page.getByRole("button",{name:"Redraw 6 visuals",exact:true});
  await open.click();
  const dialog = page.getByRole("dialog");
  for (const [index, title] of ["Opening","Process"].entries()) {
    const group = dialog.getByRole("group",{name:new RegExp(title)});
    assert.deepEqual(await group.getByRole("listitem").allTextContents().then(rows => rows.map(row => row.match(/Diagram of item (\d+)/)?.[1])), index ? ["2","4","6"] : ["1","3","5"]);
  }
  await dialog.getByRole("button",{name:"Not now"}).click();
  assert.equal(applies,0);
  await open.click();
  await Promise.all([page.waitForResponse("**/api/episodes/fixture/apply"),dialog.getByRole("button",{name:"Redraw 6 visuals"}).click()]);
  assert.equal(applies,1);
  await page.goto(url.href+"?single");
  await page.getByRole("button",{name:"Redraw 1 visual",exact:true}).waitFor();
  await page.goto(url.href+"?mixed");
  await page.getByRole("button",{name:/Apply changes.*7/}).click();
  await dialog.getByText("1 new picture is made").waitFor();
  assert.equal(await dialog.getByRole("group",{name:/Opening/}).getByRole("listitem").count(),3);
});
