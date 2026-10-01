import {describe,it,expect,vi} from 'vitest';
import {submit,stopTarget} from '../src/operations';
import {api,ApiError} from '../src/api';
vi.mock('../src/api',async()=>{const original=await vi.importActual('../src/api');return{...original,api:vi.fn()}});

describe('uncertain operation receipts',()=>{
  it('retries a lost response with the same id and original revision',async()=>{
    const sent:any[]=[];vi.mocked(api).mockImplementation(async(_path,body)=>{
      sent.push(structuredClone(body));if(sent.length===1)throw new ApiError('lost',0);return{state:'completed'};
    });
    const payload={text:'继续',input_ids:[]};
    await expect(submit('/tasks/t/messages',payload,2,vi.fn())).rejects.toThrow('lost');
    await submit('/tasks/t/messages',payload,8,vi.fn());
    expect(sent[0]).toEqual(sent[1]);
    await submit('/tasks/t/messages',payload,9,vi.fn());
    expect(sent[2].request_id).not.toBe(sent[1].request_id);
  });
  it('updates revision only after an explicit conflict',async()=>{
    const sent:any[]=[];vi.mocked(api).mockImplementation(async(_path,body)=>{
      sent.push(structuredClone(body));if(sent.length===1)throw new ApiError('changed',409,'revision_conflict');return{state:'completed'};
    });
    await submit('/tasks/t/actions',{kind:'select',payload:{ids:['p']}},2,async()=>3);
    expect(sent.map(s=>s.expected_revision)).toEqual([2,3]);
    expect(sent[0].request_id).toBe(sent[1].request_id);
  });
  it('a lost stop response for an earlier turn cannot swallow the next stop',async()=>{
    const sent:any[]=[];vi.mocked(api).mockImplementation(async(_path,body)=>{
      sent.push(structuredClone(body));if(sent.length===1)throw new ApiError('lost stop',0);return{state:'completed'};
    });
    const turn=(id:string)=>({blocks:[{block_id:id,kind:'text',body:{role:'user'}}]});
    const payload=(id:string)=>({kind:'stop',payload:{target:stopTarget(turn(id))}});
    await expect(submit('/tasks/stop/actions',payload('turn-a'),3,vi.fn())).rejects.toThrow('lost stop');
    await submit('/tasks/stop/actions',payload('turn-b'),9,vi.fn());
    expect(sent[0].request_id).not.toBe(sent[1].request_id);
  });
});
