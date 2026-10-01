import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
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
});
