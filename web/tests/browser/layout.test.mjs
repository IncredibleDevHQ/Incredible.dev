import assert from "node:assert/strict";
import test from "node:test";
import { chromium } from "playwright";
import { createServer } from "vite";

test("chapter duration and visual layout choices follow the saved episode", async t => {
  const server = await createServer({server:{host:"127.0.0.1",port:0},logLevel:"error"});
  t.after(() => server.close());
  await server.listen();
  const browser = await chromium.launch();
  t.after(() => browser.close());
  const page = await browser.newPage();
  page.setDefaultTimeout(3000);
  await page.goto(new URL("tests/browser/layout.html", server.resolvedUrls.local[0]).href);
  const chapter = page.getByRole("button",{name:/Chapter title/});
  await chapter.getByText("0:23",{exact:true}).waitFor();
  const film = page.getByRole("button",{name:/The film/});
  assert.equal(await film.locator("time.ep-slide-duration").textContent(), "0:23");
  const shape = page.getByRole("combobox",{name:/Video box shape/});
  assert.match(await shape.textContent(), /Rounded/);
  const endpoint = "**/api/episodes/fixture/choices";
  await page.route(endpoint, route => route.fulfill({json:{}}));
  async function choose(control) {
    const request = page.waitForRequest(endpoint);
    await control.click();
    return (await request).postDataJSON();
  }
  const spotlight = page.getByRole("radio", {name:/Number spotlight/});
  assert.deepEqual(await choose(spotlight), {frames:{line:{presence:"content",layout:"number-spotlight"}}});
  await shape.click();
  assert.deepEqual(await choose(page.getByRole("option",{name:"Circle",exact:true})),{frames:{line:{window_shape:"circle"}}});
  await shape.click();
  assert.deepEqual(await choose(page.getByRole("option",{name:"Layout default",exact:true})),{frames:{line:{window_shape:null}}});
  const faces = page.getByRole("group",{name:"Episode presenter portrait"});
  assert.equal(await faces.locator('button[aria-pressed]').count(),2);
  assert.equal(await faces.getByRole("button",{name:"June",exact:true}).getAttribute("aria-pressed"),"true");
  assert.equal(await faces.getByRole("button",{name:/previous portraits|next portraits/i}).count(),0);
  assert.deepEqual(await choose(faces.getByRole("button",{name:"Mira",exact:true})),{settings:{portrait:"mira"}});
});
