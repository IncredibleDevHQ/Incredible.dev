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
  const shapes = page.getByRole("radiogroup",{name:"Video box shape"});
  assert.equal(await shapes.getByRole("radio",{name:"Rounded",exact:true}).getAttribute("aria-checked"), "true");
  const endpoint = "**/api/episodes/fixture/choices";
  await page.route(endpoint, route => route.fulfill({json:{}}));
  async function choose(control) {
    const request = page.waitForRequest(endpoint);
    await control.click();
    return (await request).postDataJSON();
  }
  assert.deepEqual(await choose(shapes.getByRole("radio",{name:"Circle",exact:true})),{frames:{line:{window_shape:"circle"}}});
  assert.deepEqual(await choose(shapes.getByRole("radio",{name:"Layout default",exact:true})),{frames:{line:{window_shape:null}}});
  const faces = page.getByRole("group",{name:"Episode presenter portrait"});
  assert.equal(await faces.locator('button[aria-pressed]').count(),4);
  assert.equal(await faces.getByRole("button",{name:"June",exact:true}).getAttribute("aria-pressed"),"true");
  assert.equal(await faces.getByRole("button",{name:/previous portraits|next portraits/i}).count(),0);
  assert.deepEqual(await choose(faces.getByRole("button",{name:"Kai",exact:true})),{settings:{portrait:"kai"}});
});
