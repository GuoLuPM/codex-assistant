import {test,expect} from '@playwright/test';
import {execFileSync} from 'node:child_process';

// Opt in on a prepared Windows installation. Only the model is simulated;
// the HTTP server, selection store, renderer, verifier and downloads are real.
test('repeated exports keep the latest selection and survive failures and reloads',async({page},info)=>{
  test.skip(process.env.ASSISTANT_TEST_REAL_EXPORT!=='1','Requires the local Windows PPT environment.');
  test.setTimeout(300_000);
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/#start=browser-fixture');
  const snapshot=()=>page.evaluate(async()=>await(await fetch('/api/tasks/'+localStorage.getItem('assistant-task'))).json());
  const exportButton=()=>page.getByRole('button',{name:'做成图册',exact:true});
  await expect(page.getByRole('checkbox')).toHaveCount(2);
  await page.getByRole('checkbox').first().check();
  // Two consecutive fast failures exercise identical terminal statuses, which
  // can arrive in one SSE batch without a render of the intermediate state.
  for(let attempt=0;attempt<2;attempt++){
    await exportButton().click();
    await expect.poll(async()=>(await snapshot()).progress?.state,{timeout:15_000}).toBe('failed');
    expect(errors).toEqual([]);
    await expect(page.getByRole('alert')).toContainText('这次图册没能生成');
    await expect(exportButton()).toBeEnabled();
  }
  let previousJob=(await snapshot()).progress.job_id;
  const timings:number[]=[];
  for(let round=0;round<12;round++){
    if(round){
      await page.getByRole('button',{name:'重新挑选'}).click();
      await expect(page.getByRole('checkbox').first()).toBeEnabled();
    }
    // Add network latency to the last selection write; exporting must flush it.
    await page.route('**/actions',async route=>{
      if(route.request().postDataJSON()?.kind==='select')await new Promise(r=>setTimeout(r,120));
      await route.continue();
    });
    const wanted=round%3===0?[0]:round%3===1?[1]:[0,1];
    for(let i=0;i<2;i++)await page.getByRole('checkbox').nth(i).setChecked(wanted.includes(i));
    const started=Date.now();
    const accepted=page.waitForResponse(r=>r.url().endsWith('/actions')&&r.request().postDataJSON()?.kind==='export'&&r.status()===200);
    await exportButton().evaluate((el:HTMLButtonElement)=>{el.click();el.click()});
    const response=await accepted;
    const receipt=await response.json();
    const job=receipt.result.job_id;
    expect(job).not.toBe(previousJob);previousJob=job;
    // Replay an accepted HTTP operation as if its first response had been lost.
    const replays=await Promise.all(Array.from({length:5},()=>page.request.post(response.url(),{
      data:response.request().postDataJSON(),headers:{Origin:new URL(page.url()).origin},
    })));
    for(const replay of replays){expect(replay.status()).toBe(200);expect((await replay.json()).result.job_id).toBe(job)}
    await page.unroute('**/actions');
    if(round%2===0)await page.reload();
    await expect.poll(async()=>(await snapshot()).progress.state,{timeout:60_000}).toBe('completed');
    await expect(page.getByRole('link',{name:'保存',exact:true})).toHaveCount(1);
    const state=await snapshot();
    const selection=state.blocks.find((b:any)=>b.kind==='products').body;
    expect(selection.selected_ids).toEqual(wanted.map(i=>selection.items[i].id));
    expect(state.thread_id).toBeNull();
    expect(state.artifact_ids).toHaveLength(round+1);
    const downloadPromise=page.waitForEvent('download');
    await page.getByRole('link',{name:'保存',exact:true}).click();
    const download=await downloadPromise;
    expect(await download.failure()).toBeNull();
    expect(download.suggestedFilename()).toBe('产品图册.pptx');
    const destination=info.outputPath('export-'+round+'.pptx');
    await download.saveAs(destination);
    const inspected=JSON.parse(execFileSync(process.env.ASSISTANT_TEST_PYTHON??'python',['-c',
      'import json,re,sys,zipfile,xml.etree.ElementTree as E; z=zipfile.ZipFile(sys.argv[1]); files=sorted(n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide[0-9]+\\.xml",n)); print(json.dumps([[e.text for e in E.fromstring(z.read(n)).iter() if e.tag.endswith("}t") and e.text] for n in files]))',destination],{encoding:'utf8'}));
    expect(inspected).toHaveLength(wanted.length);
    for(const [i,slide] of inspected.entries()){
      const item=selection.items[wanted[i]];
      expect(slide.join('')).toContain(item.name);
      expect(slide.join('')).toContain(String(item.prices[0].value));
    }
    timings.push(Date.now()-started);
    console.info(`Verified PPT ${round+1}/12 (${wanted.length} products).`);
  }
  await page.screenshot({path:info.outputPath('completed.png'),fullPage:true});
  // Stopping a real renderer must retain the prior verified, downloadable file.
  const lastUrl=await page.getByRole('link',{name:'保存',exact:true}).getAttribute('href');
  const before=await(await page.request.get(lastUrl!)).body();
  await page.getByRole('button',{name:'重新挑选'}).click();
  await exportButton().click();
  await page.getByRole('button',{name:'停止',exact:true}).click();
  await expect.poll(async()=>(await snapshot()).progress.state).toBe('failed');
  await expect(page.getByRole('alert')).toContainText('已经停止生成');
  const after=await page.request.get(lastUrl!);expect(after.status()).toBe(200);
  expect(await after.body()).toEqual(before);
  await page.reload();
  await expect(exportButton()).toBeEnabled();
  expect(errors).toEqual([]);
  await info.attach('timings',{body:JSON.stringify({completed:12,replayed_requests:60,seconds:timings.map(t=>t/1000)}),contentType:'application/json'});
});
