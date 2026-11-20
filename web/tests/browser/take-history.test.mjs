import assert from 'node:assert/strict';
import test from 'node:test';
import {chromium} from 'playwright';
import {createServer} from 'vite';
test('take history previews without selecting and explicitly restores a named recording',async t=>{
 const server=await createServer({server:{host:'127.0.0.1',port:0},logLevel:'error'});
 t.after(()=>server.close());await server.listen();
 const browser=await chromium.launch();t.after(()=>browser.close());
 const page=await browser.newPage();page.setDefaultTimeout(4000);
 let selected=0;
 await page.route('**/api/episodes/fixture/takes/old/keep',r=>{selected++;return r.fulfill({json:{}})});
 await page.goto(new URL('tests/browser/take-history.html',server.resolvedUrls.local[0]).href);
 await page.getByText('Calm delivery',{exact:true}).waitFor();
 assert.equal(await page.getByText('Other chapter',{exact:true}).count(),0);
 assert.equal(await page.getByText('In use',{exact:true}).count(),1);
 await page.getByRole('button',{name:'Preview Calm delivery'}).click();
 assert.equal(await page.getByLabel('Recording preview: Calm delivery').getAttribute('src'),'/old.webm');
 assert.equal(selected,0);
 await page.getByRole('button',{name:'Use this take'}).click();
 assert.equal(selected,1);
 // the camera's file of a studio take, from its card or a file; a camera's own take says where it came from
 assert.equal(await page.getByRole('button',{name:'Camera file'}).count(),1);
 assert.equal(await page.getByText('4K',{exact:true}).count(),1);
 await page.getByText('C0012.MP4, matched to Calm delivery',{exact:false}).waitFor();
});
