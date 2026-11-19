import assert from 'node:assert/strict';
import test from 'node:test';
import {chromium} from 'playwright';
import {createServer} from 'vite';

test('recording script keeps every line available and follows only the current line',async t=>{
 const server=await createServer({server:{host:'127.0.0.1',port:0},logLevel:'error'});
 t.after(()=>server.close());await server.listen();
 const browser=await chromium.launch();t.after(()=>browser.close());
 const page=await browser.newPage();page.setDefaultTimeout(4000);
 await page.goto(new URL('tests/browser/recording-script.html',server.resolvedUrls.local[0]).href);
 const script=page.getByRole('list',{name:'Chapter script'});
 await script.waitFor();
 assert.equal(await script.getByRole('listitem').count(),6);
 assert.match(await script.locator('[aria-current="step"]').innerText(),/Line 1/);
 assert.equal(await script.locator('[data-active]').count(),1);
 await page.getByRole('button',{name:'Advance'}).click();
 const active=script.locator('[aria-current="step"]');
 assert.match(await active.innerText(),/Line 5/);
 assert.equal(await script.getByRole('listitem').count(),6);
 assert.ok(await script.evaluate(el=>el.scrollTop>0));
 assert.ok(await active.evaluate(el=>{const r=el.getBoundingClientRect(), p=el.parentElement.getBoundingClientRect();return r.top>=p.top && r.top<p.bottom;}));
});
