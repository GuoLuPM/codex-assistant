import {api,ApiError} from './api';
import type {Snapshot} from './state';

// A message id survives the interval before native turn/start is acknowledged.
export function stopTarget(state:Pick<Snapshot,'blocks'|'progress'>){return{
  message_id:state.blocks.filter(b=>b.kind==='text'&&b.body.role==='user').at(-1)?.block_id??null,
  job_id:state.progress?.state==='running'?state.progress.job_id:null,
}}

// An uncertain response keeps its original id and revision across retries/reloads.
// Only a confirmed precondition conflict permits changing the revision.
export async function submit(path:string,payload:Record<string,unknown>,revision:number,reload:()=>Promise<number>){
  const key='assistant-pending:'+JSON.stringify([path,payload]);
  let request;
  try{request=JSON.parse(localStorage.getItem(key)??'null')}catch{request=null}
  request??={...payload,request_id:crypto.randomUUID(),expected_revision:revision};
  localStorage.setItem(key,JSON.stringify(request));
  try{
    let result;
    try{result=await api(path,request)}catch(e){
      if(!(e instanceof ApiError)||e.code!=='revision_conflict')throw e;
      request.expected_revision=await reload();
      localStorage.setItem(key,JSON.stringify(request));
      result=await api(path,request);
    }
    localStorage.removeItem(key);
    return result;
  }catch(e){
    if(e instanceof ApiError&&e.status>=400&&e.status<500)localStorage.removeItem(key);
    throw e;
  }
}
