import assert from 'node:assert/strict';
import test from 'node:test';
import {chromium} from 'playwright';
import {createServer} from 'vite';

test('take review keeps the script and version name while saving and recovering from failure',async t=>{
 const server=await createServer({server:{host:'127.0.0.1',port:0},logLevel:'error'});
 t.after(()=>server.close());await server.listen();
 const browser=await chromium.launch();t.after(()=>browser.close());
 const page=await browser.newPage();page.setDefaultTimeout(2500);
 await page.goto(new URL('tests/browser/take-review.html',server.resolvedUrls.local[0]).href);
 await page.getByRole('heading',{name:'Review your take'}).waitFor();
 assert.equal(await page.getByRole('list',{name:'Recorded script'}).getByRole('listitem').count(),2);
 const name=page.getByRole('textbox',{name:'Version name'});
 await name.fill('Calm delivery');
 assert.equal(await name.getAttribute('maxlength'),'120');
 await page.getByRole('button',{name:'Save take',exact:true}).click();
 assert.equal(await name.isEnabled(),false);
 assert.equal(await page.getByRole('button',{name:'Record again'}).isEnabled(),false);
 await page.getByRole('alert').filter({hasText:'Upload failed'}).waitFor();
 assert.equal(await name.inputValue(),'Calm delivery');
 assert.equal(await page.getByRole('button',{name:'Save take',exact:true}).isEnabled(),true);
 await page.getByRole('button',{name:'Record again'}).click();
 await page.getByText('Retake requested').waitFor();
});
