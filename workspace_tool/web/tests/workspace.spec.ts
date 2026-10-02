import {test,expect} from '@playwright/test';

test('real page preserves selection, input, layout and local-only actions',async({page})=>{
  test.skip(process.env.ASSISTANT_TEST_REAL_EXPORT==='1','The real export stress test covers successful rendering separately.');
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});
  await page.goto('/#start=browser-fixture');
  const input=page.getByRole('textbox',{name:'说说您的需求'});
  await expect(page.getByRole('checkbox')).toHaveCount(2);
  await expect(page.locator('details[open]')).toHaveCount(0);
  await page.getByRole('checkbox').first().check();
  await expect(page.getByText('已选 1 款',{exact:true})).toBeVisible();
  await page.waitForFunction(async()=>{
    const s=await(await fetch('/api/tasks/'+localStorage.getItem('assistant-task'))).json();
    return s.blocks.find((b:any)=>b.kind==='products').body.selected_ids.length===1;
  });
  await input.fill('我还想补一句');await page.reload();
  await expect(input).toHaveValue('我还想补一句');await expect(page.getByRole('checkbox').first()).toBeChecked();
  await page.getByRole('button',{name:'全部展开'}).click();await expect(page.locator('details[open]')).toHaveCount(2);
  await page.getByRole('button',{name:'全部收起'}).click();
  await input.focus();await input.evaluate(el=>{el.setAttribute('data-stable','yes')});
  await input.dispatchEvent('compositionstart');await input.dispatchEvent('keydown',{key:'Enter',isComposing:true,keyCode:229});await input.dispatchEvent('compositionend');
  await expect(input).toHaveValue('我还想补一句');await expect(input).toHaveAttribute('data-stable','yes');
  await page.getByRole('button',{name:'分享商品'}).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.getByRole('button',{name:'确认分享'})).toBeVisible();
  await page.getByRole('button',{name:'关闭'}).click();
  await page.getByRole('button',{name:'做成图册',exact:true}).click();
  await expect(page.getByRole('button',{name:'停止',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'停止',exact:true}).click();
  await expect(page.getByRole('button',{name:'重新挑选'})).toBeVisible();
  await expect(page.getByRole('checkbox').first()).toBeDisabled();
  await page.reload();
  await page.getByRole('button',{name:'重新挑选'}).click();
  await expect(page.getByRole('checkbox').first()).toBeEnabled();
  await expect(page.getByRole('checkbox').first()).toBeChecked();
  await page.getByRole('checkbox').nth(1).check();
  await expect(page.getByText('已选 2 款',{exact:true})).toBeVisible();
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.evaluate(()=>document.documentElement.style.fontSize='44px');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  const snapshot=await page.evaluate(async()=>await(await fetch('/api/tasks/'+localStorage.getItem('assistant-task'))).json());
  expect(snapshot.thread_id).toBeNull(); // All clicks above consumed zero model turns.
  await page.goto('/help');
  await expect(page.getByRole('heading',{name:'想办什么，直接告诉我'})).toBeVisible();
  expect(await page.evaluate(()=>getComputedStyle(document.documentElement).fontSize)).toBe('22px');
  expect(errors).toEqual([]);
});
