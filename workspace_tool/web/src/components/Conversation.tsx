import {useEffect,useRef} from 'react';
import type {Action,Snapshot} from '../state';
import {RichBlock} from './RichBlock';
import {Question} from './Question';
export function Conversation({state,onAction}:{state:Snapshot;onAction:Action}){
  const list=useRef<HTMLDivElement>(null),follow=useRef(true);
  useEffect(()=>{if(follow.current&&list.current)list.current.scrollTop=list.current.scrollHeight},[state.last_event_seq]);
  useEffect(()=>{follow.current=true;if(list.current)list.current.scrollTop=list.current.scrollHeight},[state.task_id]);
  const last=state.blocks.at(-1);
  const waiting=state.state==='running'&&!(last?.kind==='text'&&last.body.role==='assistant'&&!last.body.complete);
  const commentary=state.state==='running'&&last?.body.phase==='commentary'?last.body.text.trim():'';
  const progress=state.progress?.state==='running'?'':commentary||(waiting?'正在处理…':'');
  return <div className="conversation" ref={list} onScroll={()=>{const el=list.current;if(el)follow.current=el.scrollHeight-el.scrollTop-el.clientHeight<100}}>
    <div className="conversation-content">
      {!state.blocks.length&&<div className="welcome"><h1>今天想让我帮您做什么？</h1></div>}
      {state.blocks.filter(b=>b.body.phase!=='commentary').map(b=><RichBlock key={b.block_id} block={b} taskId={state.task_id} onAction={onAction}/>)}
      {state.pending_requests.map(q=><Question key={q.request_id} value={q} onAction={onAction}/>)}
      {progress&&<p className="progress" role="status"><span className="progress-dot"/>{progress}</p>}
      {state.progress?.state==='failed'&&<p className="error-text" role="alert">{state.progress.message}</p>}
    </div>
  </div>
}
