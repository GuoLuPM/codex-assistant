import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { Composer } from '../src/components/Composer';
import { applyEvent, type Snapshot } from '../src/state';
import { ProductPicker } from '../src/components/ProductPicker';

const empty: Snapshot = {task_id:'t',revision:0,state:'ready',title:'',blocks:[],pending_requests:[],last_event_seq:0,artifact_ids:[],model_profile:'normal',active_turn_id:null,error:null};

describe('quiet, stable interaction',()=>{
  it('composition Enter does not submit; a later Enter submits once',()=>{
    const send=vi.fn();
    render(<Composer taskId="t" busy={false} connected onSend={send} onUpload={vi.fn()} onStop={vi.fn()}/>);
    const input=screen.getByRole('textbox');
    fireEvent.change(input,{target:{value:'帮我找礼品'}});
    fireEvent.compositionStart(input);
    fireEvent.keyDown(input,{key:'Enter',isComposing:true,keyCode:229});
    expect(send).not.toHaveBeenCalled();
    fireEvent.compositionEnd(input);
    fireEvent.keyDown(input,{key:'Enter'});
    expect(send).toHaveBeenCalledTimes(1);
  });
  it('stream rerenders keep the textarea node, focus and draft',()=>{
    const props={taskId:'t',busy:false,connected:true,onSend:vi.fn(),onUpload:vi.fn(),onStop:vi.fn()};
    const {rerender}=render(<Composer {...props}/>);
    const input=screen.getByRole('textbox'); input.focus();
    fireEvent.change(input,{target:{value:'我还想补一句'}});
    rerender(<Composer {...props} busy/>);
    expect(screen.getByRole('textbox')).toBe(input);
    expect(document.activeElement).toBe(input);
    expect((input as HTMLTextAreaElement).value).toBe('我还想补一句');
  });
  it('event replay does not duplicate text or replace unrelated blocks',()=>{
    const a=applyEvent(empty,{task_id:'t',seq:1,revision:1,type:'text_delta',data:{block_id:'a',delta:'你好'}});
    const again=applyEvent(a,{task_id:'t',seq:1,revision:1,type:'text_delta',data:{block_id:'a',delta:'你好'}});
    expect(again).toBe(a);
    const b=applyEvent(a,{task_id:'t',seq:2,revision:2,type:'text_delta',data:{block_id:'b',delta:'新消息'}});
    expect(b.blocks[0]).toBe(a.blocks[0]);
  });
  it('selection is immediate and details stay collapsed until requested',()=>{
    const change=vi.fn(async()=>({selected_ids:['p1'],revision:1}));
    render(<ProductPicker taskId="t" value={{session_id:'s',revision:0,state:'open',title:'礼品',selected_ids:[],items:[{id:'p1',name:'茶杯',prices:[{label:'零售价',value:88}],features:'原始说明'}]}} onAction={change}/>);
    expect((screen.getByText('详情').closest('details') as HTMLDetailsElement).open).toBe(false);
    fireEvent.click(screen.getByRole('checkbox'));
    expect((screen.getByRole('checkbox') as HTMLInputElement).checked).toBe(true);
    expect(screen.getByText('已选 1 款')).toBeTruthy();
  });
  it('a quickly failed retry releases the export button even when running events are batched',async()=>{
    const value={session_id:'s',revision:1,state:'sealed',title:'礼品',selected_ids:['p1'],items:[{id:'p1',name:'茶杯',prices:[{label:'零售价',value:88}]}],export_state:'failed',export_job_id:'old-job'};
    const action=vi.fn(async()=>({job_id:'retry-job',state:'running'}));
    const {rerender}=render(<ProductPicker taskId="t" value={value} onAction={action}/>);
    fireEvent.click(screen.getByRole('button',{name:'做成图册'}));
    await waitFor(()=>expect(action).toHaveBeenCalledWith('export',{session_id:'s',revision:1}));
    // SSE can deliver running and failed in the same React render. The last
    // status is still "failed", but it belongs to a different export attempt.
    rerender(<ProductPicker taskId="t" value={{...value,export_job_id:'retry-job'}} onAction={action}/>);
    await waitFor(()=>expect(screen.getByRole('button',{name:'做成图册'}).hasAttribute('disabled')).toBe(false));
  });
  it('an export started through the conversation shows progress and locks selection',()=>{
    const value={session_id:'s',revision:1,state:'open',title:'礼品',selected_ids:['p1'],items:[{id:'p1',name:'茶杯',prices:[{label:'零售价',value:88}]}]};
    const action=vi.fn();
    const {rerender}=render(<ProductPicker taskId="t" value={value} onAction={action}/>);
    rerender(<ProductPicker taskId="t" value={{...value,export_state:'running'}} onAction={action}/>);
    expect(screen.getByRole('checkbox').hasAttribute('disabled')).toBe(true);
    expect(screen.getByRole('button',{name:'正在做成图册…'}).hasAttribute('disabled')).toBe(true);
  });
  it('exports after selecting out of order when the server returns candidate order',async()=>{
    let saves=0;
    const action=vi.fn(async(kind:string,payload:Record<string,unknown>)=>{
      if(kind==='export')return {state:'running',job_id:'ordered'};
      if(++saves>3)throw new Error('Repeated saving of the same selection');
      return {selected_ids:['p1','p2'],revision:2};
    });
    render(<ProductPicker taskId="t" value={{session_id:'s',revision:1,state:'open',title:'礼品',selected_ids:['p2'],items:[
      {id:'p1',name:'茶杯',prices:[{label:'零售价',value:88}]},
      {id:'p2',name:'礼盒',prices:[{label:'零售价',value:68}]},
    ]}} onAction={action}/>);
    fireEvent.click(screen.getByRole('checkbox',{name:'选择 茶杯'}));
    fireEvent.click(screen.getByRole('button',{name:'做成图册'}));
    await waitFor(()=>expect(action).toHaveBeenCalledWith('export',{session_id:'s',revision:2}));
    expect(saves).toBe(1);
  });
});
