import {useEffect,useRef,useState} from 'react';
import {Icon} from './Icon';
type Input={input_id:string;display_name:string};
type Props={taskId:string;busy:boolean;connected:boolean;onSend:(text:string,ids:string[])=>any;onUpload:(file:File)=>any;onStop:()=>any;onError?:(message:string)=>void};
const readDraft=(id:string)=>{try{return JSON.parse(localStorage.getItem('assistant-draft:'+id)??'{}')}catch{return {}}};
export function Composer({taskId,busy,connected,onSend,onUpload,onStop,onError}:Props){
  const [draft,setDraft]=useState<string>(()=>readDraft(taskId).text??'');
  const [files,setFiles]=useState<Input[]>(()=>readDraft(taskId).files??[]);
  const [pending,setPending]=useState(false),[uploading,setUploading]=useState(false),[error,setError]=useState(''),[drag,setDrag]=useState(false);
  const picker=useRef<HTMLInputElement>(null),text=useRef<HTMLTextAreaElement>(null),composing=useRef(false),draftNow=useRef(draft);
  draftNow.current=draft;
  useEffect(()=>{const saved=readDraft(taskId);setDraft(saved.text??'');setFiles(saved.files??[]);setError('')},[taskId]);
  useEffect(()=>{localStorage.setItem('assistant-draft:'+taskId,JSON.stringify({text:draft,files}))},[taskId,draft,files]);
  useEffect(()=>{const el=text.current;if(el){el.style.height='auto';el.style.height=Math.min(el.scrollHeight,200)+'px'}},[draft]);
  async function send(){
    if(composing.current||pending||busy||uploading||!connected||(!draft.trim()&&!files.length))return;
    setPending(true);setError('');const sent=draft,ids=files.map(f=>f.input_id);
    try{await onSend(sent,ids);if(draftNow.current===sent)setDraft('');setFiles(old=>old.filter(f=>!ids.includes(f.input_id)))}
    catch(e){onError?onError((e as Error).message):setError((e as Error).message)}finally{setPending(false);text.current?.focus()}
  }
  async function add(incoming:FileList|File[]){
    if(uploading)return;setUploading(true);setError('');
    try{for(const file of Array.from(incoming)){const ref=await onUpload(file);setFiles(old=>old.some(f=>f.input_id===ref.input_id)?old:[...old,ref])}}
    catch(e){setError((e as Error).message)}finally{setUploading(false);if(picker.current)picker.current.value=''}
  }
  return <section className={'composer-wrap'+(drag?' dragging':'')} onDragOver={e=>{e.preventDefault();setDrag(true)}} onDragLeave={()=>setDrag(false)} onDrop={e=>{e.preventDefault();setDrag(false);void add(e.dataTransfer.files)}} aria-label="和助手说话">
    {!!files.length&&<ul className="attachments">{files.map(file=><li key={file.input_id}><Icon name="file"/><span>{file.display_name}</span><button className="icon-button" aria-label={'移除 '+file.display_name} onClick={()=>setFiles(files.filter(f=>f.input_id!==file.input_id))}><Icon name="close"/></button></li>)}</ul>}
    {error&&<p role="alert" className="error-text">{error}</p>}
    <div className="composer">
      <textarea ref={text} aria-label="说说您的需求" placeholder="跟我说说…" value={draft} rows={1}
        onChange={e=>setDraft(e.target.value)} onCompositionStart={()=>{composing.current=true}} onCompositionEnd={()=>{composing.current=false}}
        onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing&&e.keyCode!==229&&!composing.current){e.preventDefault();void send()}}}/>
      <div className="composer-actions"><button className="quiet-button" onClick={()=>picker.current?.click()} disabled={uploading}><Icon name="attach"/>{uploading?'正在添加…':'加资料'}</button>
        <input ref={picker} type="file" multiple hidden onChange={e=>{if(e.target.files)void add(e.target.files)}}/>
        {busy?<button className="send-button" aria-label="停止" onClick={()=>void onStop()}><Icon name="stop"/></button>:<button className="send-button" aria-label="发送" disabled={pending||uploading||!connected||(!draft.trim()&&!files.length)} onClick={()=>void send()}><Icon name="send"/></button>}
      </div>
    </div>
  </section>
}
