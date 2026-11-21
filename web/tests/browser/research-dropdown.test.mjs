import assert from "node:assert/strict";
import test from "node:test";
import { chromium } from "playwright";
import { createServer } from "vite";

test("repository suggestions float below the search without moving the research form", async t => {
  const server = await createServer({ server: { host: "127.0.0.1", port: 0 }, logLevel: "error" });
  t.after(() => server.close());
  await server.listen();
  const browser = await chromium.launch();
  t.after(() => browser.close());
  const page = await browser.newPage();
  page.setDefaultTimeout(5000);
  const data = {
    "/api/session": { me: "you", people: [], agent: { mark: "house" } },
    "/api/channels": [{ id: "sample", name: "sample" }],
    "/api/catalog": {}, "/api/brands": { brands: [], reading: [] },
    "/api/production": { agents: [], episodes: [], jobs: [] },
    "/api/channels/sample/messages": { roots: [], threads: {}, replies: {} },
    "/api/channels/sample/canvas": [],
    "/api/research": { provider_api: true, repos: ["alpha", "beta"].map(name => ({name, path: name, branch: ""})),
      harnesses: [{ id: "codex", title: "Codex", model: "fixture", ready: true }],
      models: {codex: [{id:"", name:"Default", resolves:"fixture", efforts:["low","high"]},
        {id:"alternate",name:"Alternate model",efforts:["low","high"]}]} },
  };
  await page.route("**/api/**", route => route.fulfill({ json: data[new URL(route.request().url()).pathname] ?? {} }));
  for (const viewport of [{width:1465, height:851}, {width:390, height:700}]) {
    await page.setViewportSize(viewport);
    await page.goto(new URL("c/sample/canvas", server.resolvedUrls.local[0]).href);
    await page.getByRole("button", {name:"Start research"}).click();
    const dialog = page.getByRole("dialog", {name:"Research a repository"});
    const model = dialog.getByRole("combobox", {name: /^Model/});
    const effort = dialog.getByRole("combobox", {name: /^Effort/});
    await model.click();
    await dialog.getByRole("option", {name:"Alternate model"}).click();
    await effort.click();
    await dialog.getByRole("option", {name:"High",exact:true}).click();
    assert.match(await model.innerText(), /Alternate model/);
    assert.match(await effort.innerText(), /High/);
    await effort.click();
    await effort.press("Escape");
    assert.equal(await dialog.isVisible(), true);
    const input = dialog.getByLabel("Find a repository");
    const menu = dialog.getByRole("listbox");
    const question = dialog.getByLabel("The first question");
    const notes = dialog.getByLabel("Notes and prior research");
    assert.equal(await input.getAttribute("aria-expanded"), "false");
    const before = await question.boundingBox();
    await input.click();
    await menu.waitFor();
    const field = await input.boundingBox();
    const popup = await menu.boundingBox();
    assert.ok(popup.y >= field.y + field.height && popup.y < field.y + field.height + 24);
    assert.deepEqual(await question.boundingBox(), before);
    assert.ok((await notes.boundingBox()).height > before.height);
    await input.press("Escape");
    assert.equal(await menu.count(), 0);
    await input.press("ArrowDown");
    await menu.waitFor();
    await input.press("Tab");
    assert.equal(await menu.count(), 0);
    await input.click();
    await dialog.getByRole("option", {name:"alpha"}).click();
    const chip = dialog.getByRole("button", {name:"Remove alpha"});
    await chip.waitFor();
    const fill = el => getComputedStyle(el).backgroundColor;
    assert.notEqual(await chip.evaluate(fill), await dialog.evaluate(fill));
    assert.notEqual(await chip.evaluate(fill), "rgba(0, 0, 0, 0)");
    assert.equal(await menu.count(), 0);
    await input.click();
    await notes.click();
    assert.equal(await menu.count(), 0);
    await question.fill("Compare these repositories");
    const request = page.waitForRequest(req => req.method() === "POST" && req.url().endsWith("/channels/sample/research"));
    await dialog.getByRole("button", {name:"Start research"}).click();
    const body = (await request).postDataJSON();
    assert.equal(body.model, "alternate");
    assert.equal(body.effort, "high");
  }
});
