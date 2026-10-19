/* Optional browser QA. Requires Playwright on the development machine. */
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

(async () => {
  const file = process.argv[2];
  if (!file) throw new Error('Usage: node tools/browser_check.cjs scan.pdf');
  await fs.mkdir('test-output',{recursive:true});
  const browser = await chromium.launch({headless:true,channel:process.env.SCANSPLIT_BROWSER_CHANNEL || 'chrome'});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1120},acceptDownloads:true});
    const errors = []; page.on('pageerror',error => errors.push(error.message));
    await page.goto(process.env.SCANSPLIT_TEST_URL || 'http://127.0.0.1:18767');
    await page.locator('#file-input').setInputFiles(file);
    await page.locator('#workspace').waitFor({state:'visible',timeout:60000});
    await page.waitForFunction(() => document.getElementById('preview-image').naturalWidth > 0,null,{timeout:90000});
    assert.equal(await page.locator('#ocr-toggle').isChecked(),true);
    assert.ok((await page.locator('#ocr-card').getAttribute('class')).includes('active'));
    const pageCount = await page.locator('.page-select').count();
    await page.locator('#select-all-pages').check();
    assert.equal(await page.locator('.page-select:checked').count(),pageCount);
    await page.locator('#select-all-pages').uncheck();
    assert.equal(await page.locator('.page-select:checked').count(),0);
    await page.locator('#card-0 .page-select').check();
    if (pageCount > 1) assert.equal(await page.locator('#select-all-pages').evaluate(e => e.indeterminate),true);
    const activeColor = await page.locator('#ocr-card').evaluate(e => getComputedStyle(e).backgroundColor);
    await page.locator('#page-mode').selectOption('right');
    const box = await page.locator('#sheet').boundingBox();
    const divider = await page.locator('#divider').boundingBox();
    await page.mouse.move(divider.x+divider.width/2,box.y+box.height/2);
    await page.mouse.down(); await page.mouse.move(box.x+box.width*.57,box.y+box.height/2,{steps:8}); await page.mouse.up();
    assert.ok(Number(await page.locator('#cut-range').inputValue()) > 55);
    await page.locator('#center-line').click(); assert.equal(Number(await page.locator('#cut-range').inputValue()),50);
    await page.locator('#divider').focus(); await page.keyboard.press('ArrowLeft');
    assert.equal(Number(await page.locator('#cut-range').inputValue()),49.5);
    await page.locator('#center-line').click();
    if (await page.locator('.page-card').count() > 1) {
      await page.locator('#card-1 .page-select').check();
      await page.locator('#apply-selection').click();
      assert.equal(await page.locator('#card-1 small').textContent(),'Nur rechts');
      await page.locator('#card-1 button').click(); await page.locator('#page-mode').selectOption('split');
      await page.locator('#card-0 button').click();
    }
    await page.locator('#rotate-page').click(); await page.locator('#rotate-page').click();
    await page.locator('#rotate-page').click(); await page.locator('#rotate-page').click();
    await page.locator('#preview-loading').waitFor({state:'hidden',timeout:90000});
    await page.screenshot({path:'test-output/desktop-ocr-active.png',fullPage:true});
    await page.locator('#ocr-toggle').uncheck();
    await page.waitForFunction(color => getComputedStyle(document.getElementById('ocr-card')).backgroundColor !== color,activeColor);
    assert.notEqual(await page.locator('#ocr-card').evaluate(e => getComputedStyle(e).backgroundColor),activeColor);
    await page.locator('#export-button').click();
    await page.locator('#download-result').waitFor({state:'visible',timeout:120000});
    const downloadEvent = page.waitForEvent('download'); await page.locator('#download-result').click();
    const download = await downloadEvent; await download.saveAs('test-output/browser-result.pdf');
    await page.reload(); await page.locator('#download-result').waitFor({state:'visible',timeout:30000});
    assert.equal(await page.locator('#ocr-toggle').isChecked(),false);
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:'test-output/mobile.png',fullPage:true});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth),false,'Mobile layout overflow');
    assert.deepEqual(errors,[],'Browser JavaScript errors');
    await fs.writeFile('test-output/browser-report.json',JSON.stringify({passed:true,tested:['upload','preview','red default OCR','drag divider','keyboard divider','multi select','rotation','OCR toggle','export','download','reload','mobile'],sourcePages:await page.locator('.page-card').count()},null,2));
    console.log('Browser QA passed; screenshots and downloaded PDF in test-output/');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
