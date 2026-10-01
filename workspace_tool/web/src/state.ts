export interface Block {block_id:string;kind:string;revision?:number;body:Record<string,any>;actions?:string[]}
export interface Snapshot {task_id:string;revision:number;state:string;title:string;blocks:Block[];pending_requests:any[];last_event_seq:number;artifact_ids:string[];model_profile:string;active_turn_id:string|null;error:string|null;thread_id?:string;progress?:{state:string;message:string;job_id:string}}
export interface UiEvent {task_id:string;seq:number;revision:number;type:string;data:any}
export interface Product {id:string;name:string;model?:string;variant?:string;prices:{label:string;value:string|number}[];features?:string;image_url?:string;source_file?:string;locator?:string;category?:string;tags?:any[]}
export interface Selection {session_id:string;revision:number;state:string;title:string;selected_ids:string[];items:Product[];caption?:string;export_state?:string}
export type Action = (kind:string,payload:Record<string,unknown>)=>Promise<any>;
export function applyEvent(previous:Snapshot,event:UiEvent):Snapshot {
  if(event.task_id!==previous.task_id||event.seq<=previous.last_event_seq)return previous;
  const s={...previous,revision:Math.max(previous.revision,event.revision),last_event_seq:event.seq};
  const d=event.data;
  switch(event.type){
    case 'text_delta':case 'text_done':case 'user_message':{
      const i=s.blocks.findIndex(b=>b.block_id===d.block_id);
      const existing:Block=i<0?{block_id:d.block_id,kind:'text',body:{text:'',role:event.type==='user_message'?'user':'assistant'}}:s.blocks[i];
      const block={...existing,body:{...existing.body,text:event.type==='text_delta'?existing.body.text+d.delta:d.text,complete:event.type!=='text_delta',phase:d.phase??existing.body.phase,input_ids:d.input_ids??existing.body.input_ids}};
      s.blocks=i<0?[...s.blocks,block]:s.blocks.map((b,index)=>index===i?block:b);break;
    }
    case 'block':s.blocks=s.blocks.some(b=>b.block_id===d.block_id)?s.blocks.map(b=>b.block_id===d.block_id?d:b):[...s.blocks,d];break;
    case 'selection':s.blocks=s.blocks.map(b=>b.kind==='products'&&b.body.session_id===d.session_id?{...b,body:{...b.body,...d}}:b);break;
    case 'title':s.title=d.title;break;
    case 'thread':s.thread_id=d.thread_id;break;
    case 'turn_started':s.state='running';s.active_turn_id=d.turn_id;s.error=null;break;
    case 'turn_ended':s.state=({completed:s.artifact_ids.length?'completed':'ready',interrupted:'interrupted',failed:'failed'} as Record<string,string>)[d.status]??'failed';s.active_turn_id=null;s.pending_requests=[];s.error=d.message??null;break;
    case 'error':s.state='failed';s.error=d.message;s.active_turn_id=null;break;
    case 'question':s.pending_requests=[...s.pending_requests.filter(q=>q.request_id!==d.request_id),d];s.state='awaiting_user';break;
    case 'answered':s.pending_requests=s.pending_requests.filter(q=>q.request_id!==d.request_id);s.state=s.pending_requests.length?'awaiting_user':'running';break;
    case 'progress':s.progress=d;break;
    case 'artifact':s.artifact_ids=Array.from(new Set([...s.artifact_ids,d.artifact_id]));if(!s.active_turn_id)s.state='completed';break;
  }
  return s;
}
