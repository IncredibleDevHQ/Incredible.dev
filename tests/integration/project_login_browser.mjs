// Driven by test_project_login_browser.py against the real Studio HTTP server.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
const { chromium } = createRequire(new URL("../../web/package.json", import.meta.url))("playwright");
const [root, ownerId, guestId] = process.argv.slice(2);
const project = id => root.replace("127.0.0.1", id + ".localhost");
const ownerEmail = ownerId + "@example.com";
const guestEmail = guestId + "@example.com";
const browser = await chromium.launch();
try {
  const owner = await browser.newContext({permissions:["clipboard-read","clipboard-write"]});
  const page = await owner.newPage();
  const guest = await browser.newContext();
  const member = await guest.newPage();
  async function signup(tab, email, id) {
    await tab.getByRole("button",{name:"Create an account"}).click();
    assert.equal(new URL(tab.url()).origin, root);
    await tab.getByLabel("Email",{exact:true}).fill(email);
    await tab.getByLabel("Password",{exact:true}).fill("test-password");
    await tab.getByRole("button",{name:"Create account",exact:true}).click();
    await tab.getByText(/Check your email to confirm/).waitFor();
    await tab.goto(root + "/api/auth/callback?code=" + id);
  }
  async function signIn(tab, email) {
    await tab.getByLabel("Email or username").fill(email);
    assert.equal(new URL(tab.url()).origin, root);
    await tab.getByLabel("Password",{exact:true}).fill("test-password");
    await tab.getByRole("button",{name:"Sign in",exact:true}).click();
  }
  async function workspace(tab, origin) {
    await tab.locator(".whoami").waitFor();
    assert.equal(new URL(tab.url()).origin, origin);
  }
  await page.goto(root);
  await signup(page,ownerEmail,ownerId);
  await page.getByLabel("Organization name").fill("Design team");
  await page.getByRole("button",{name:"Open workspace"}).click();
  await workspace(page,project("design-team"));
  await page.goto(project("design-team")+"/settings/organization");
  assert.equal(await page.getByLabel("Organization name").inputValue(),"Design team");
  await page.getByRole("button",{name:"Invite member"}).click();
  await page.getByLabel("Invite by email").fill(guestEmail);
  await page.getByRole("button",{name:"Send invitation"}).click();
  await page.getByRole("button",{name:"Actions for "+guestEmail}).click();
  await page.getByRole("menuitem",{name:"Copy invite link"}).click();
  await page.getByText("Invite link copied.").waitFor();
  const link = await page.evaluate(()=>navigator.clipboard.readText());
  assert.equal(new URL(link).origin,project("design-team"));
  // Previously issued UUID invitations reach the named project after authentication.
  await member.goto(link.replace(project("design-team"),project(ownerId)));
  await signup(member,guestEmail,guestId);
  await member.getByRole("button",{name:"Accept invitation"}).waitFor();
  assert.equal(await member.getByRole("heading",{name:"Design team"}).count(),1);
  await member.getByRole("button",{name:"Accept invitation"}).click();
  await member.waitForURL(project("design-team")+"/settings/organization");
  await member.getByText("Return to my project").waitFor();
  // A fresh browser has no project cookies or local storage to suggest a destination.
  await guest.close();
  const returning = await browser.newContext();
  const tab = await returning.newPage();
  await tab.goto(root); await signIn(tab,guestEmail); await workspace(tab,project("design-team"));
  const deep = project("workspace")+"/settings/profile";
  await tab.goto(project(guestId)+"/settings/profile"); await tab.getByRole("heading",{name:"Profile settings"}).waitFor();
  assert.equal(tab.url(),deep);
  const nonceCookies = await returning.cookies();
  assert.ok(nonceCookies.find(c=>c.name==="incredible-refresh" && c.domain==="127.0.0.1"));
  assert.ok(!nonceCookies.some(c=>["incredible-access","incredible-refresh"].includes(c.name) && c.domain.endsWith(".localhost")));
  await tab.goto(project("design-team")+"/settings/organization");
  await tab.getByText("Return to my project").waitFor();
  await page.reload(); await page.getByRole("button",{name:"Actions for "+guestEmail}).click();
  await page.getByRole("menuitem",{name:"Remove access"}).click();
  await page.getByRole("button",{name:"Confirm removal"}).click();
  await page.getByText("Project access updated.").waitFor();
  await tab.goto(root); await workspace(tab,project("workspace"));
  await page.getByLabel("Organization name").fill("Design House");
  await page.getByRole("button",{name:"Save changes"}).click();
  await page.waitForURL(project("design-house")+"/settings/organization");
  await page.getByRole("heading",{name:"General settings"}).waitFor();
  const bookmark = "/settings/profile?from=bookmark";
  // The settings router removes unknown query parameters after the page opens.
  const migrated = page.waitForRequest(req => req.isNavigationRequest() && req.url() === project("design-house")+bookmark);
  await page.goto(project("design-team")+bookmark);
  await migrated;
  await page.getByRole("heading",{name:"Profile settings"}).waitFor();
  assert.equal(page.url(),project("design-house")+"/settings/profile");
  // The project logout also ends the root session.
  await tab.locator(".whoami").click();
  await tab.getByRole("button",{name:"Log out"}).click();
  await tab.getByLabel("Email or username").waitFor();
  assert.equal(new URL(tab.url()).origin,root);
  // The hosted consent page is simulated; Studio handles the real PKCE callback and handoff.
  await tab.goto(deep);
  await tab.getByRole("button",{name:"Continue with Google"}).click();
  await tab.getByRole("heading",{name:"Profile settings"}).waitFor();
  assert.equal(tab.url(),deep);
} finally {
  await browser.close();
}
