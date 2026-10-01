import {useCallback,useEffect,useRef,useState} from 'react';
import {api,uploadFile} from './api';
import {submit,stopTarget} from './operations';
import {applyEvent,type Snapshot,type Action} from './state';
import {Composer} from './components/Composer';
import {Conversation} from './components/Conversation';
import {Dialog} from './components/Dialog';
import {Icon} from './components/Icon';

export function App(){
  const [state,setState]=useState<Snapshot|null>(null),[status,setStatus]=useState<any>(null),[notice,setNotice]=useState(''),[offline,setOffline]=useState(false);
  const [panel,setPanel]=useState<'history'|'settings'|null>(null),[recent,setRecent]=useState<any[]>([]),[profile,setProfile]=useState(localStorage.getItem('assistant-profile')??'normal');
  const current=useRef(state),navigation=useRef(0);current.current=state;
  const update=useCallback((value:Snapshot|((s:Snapshot)=>Snapshot))=>setState(old=>{const next=typeof value==='function'?(old?value(old):null):value;current.current=next;return next}),[]);
  async function choose(tid:string){const intent=++navigation.current;const next=await api<Snapshot>('/api/tasks/'+tid);if(intent!==navigation.current)return;update(next);localStorage.setItem('assistant-task',tid);setNotice('');setPanel(null)}
  async function fresh(){const intent=++navigation.current;const next=await api<Snapshot>('/api/tasks',{model_profile:profile});if(intent!==navigation.current)return;update(next);localStorage.setItem('assistant-task',next.task_id);setPanel(null);setNotice('')}
  useEffect(()=>{let active=true;(async()=>{
    const token=new URLSearchParams(location.hash.slice(1)).get('start');
    if(token){history.replaceState(null,'',location.pathname);await api('/api/bootstrap',{token})}
    const [readiness,list]=await Promise.all([api('/api/status'),api('/api/tasks')]);
    if(!active)return;setStatus(readiness);setRecent(list);
    const previous=localStorage.getItem('assistant-task');
    const tid=list.find((t:any)=>t.task_id===previous)?.task_id??list[0]?.task_id;
    if(tid)await choose(tid);else await fresh();
  })().catch(e=>{if(active)setNotice(e.message)});return()=>{active=false}},[]);
  useEffect(()=>{if(!state)return;const tid=state.task_id;
    const source=new EventSource(`/api/tasks/${tid}/events?after=${state.last_event_seq}`);
    source.onopen=()=>setOffline(false);source.onerror=()=>setOffline(true);
    source.onmessage=e=>{const event=JSON.parse(e.data);update(s=>applyEvent(s,event));if(event.type==='error'||event.type==='notice'||event.type==='turn_ended'&&event.data.message)setNotice(event.data.message)};
    return()=>source.close();
  },[state?.task_id,update]);
  useEffect(()=>{if(status?.ready)return;const timer=setInterval(()=>{void api('/api/status').then(setStatus).catch(()=>{})},2000);return()=>clearInterval(timer)},[status?.ready]);
  const action=useCallback<Action>(async(kind,payload)=>{
    const tid=state?.task_id;if(!tid)throw new Error('页面还在打开，请稍等。');
    const s=current.current?.task_id===tid?current.current:await api<Snapshot>(`/api/tasks/${tid}`);
    const receipt=await submit(`/api/tasks/${tid}/actions`,{kind,payload},s.revision,async()=>{
      const fresh=await api<Snapshot>(`/api/tasks/${tid}`);update(old=>old.task_id===tid?fresh:old);return fresh.revision;
    });
    if(receipt.task_revision)update(old=>old.task_id===tid?{...old,revision:Math.max(old.revision,receipt.task_revision)}:old);
    if(receipt.state==='failed')throw new Error(receipt.result?.error??'这一步还没完成。');
    return receipt.result;
  },[state?.task_id,update]);
  async function send(text:string,input_ids:string[]){
    const s=current.current;if(!s)return;
    setNotice('');
    const receipt=await submit(`/api/tasks/${s.task_id}/messages`,{text,input_ids},s.revision,async()=>{
      const fresh=await api<Snapshot>(`/api/tasks/${s.task_id}`);update(old=>old.task_id===s.task_id?fresh:old);return fresh.revision;
    });
    if(receipt.task_revision)update(old=>old.task_id===s.task_id?{...old,revision:Math.max(old.revision,receipt.task_revision)}:old);
    if(receipt.state==='failed')throw new Error(receipt.result?.error??'这一步还没完成。');
  }
  async function historyPanel(){setRecent(await api('/api/tasks'));setPanel('history')}
  const connectionMessage=status&&!status.connected?(status.error||'正在连接助手…'):status&&!status.logged_in?'请先在 Codex 中登录，然后重新打开工作台。':'';
  return <main className="app-shell">
    <header className="topbar"><button className="icon-button" aria-label="最近办的事" onClick={()=>void historyPanel().catch(e=>setNotice(e.message))}><Icon name="menu"/></button><div className="task-title">{state?.blocks.length?state.title:''}</div><button className="icon-button" aria-label="设置和帮助" onClick={()=>setPanel('settings')}><Icon name="more"/></button></header>
    {state?<Conversation state={state} onAction={action}/>:<div className="loading-screen" role="status">{notice?'':'正在打开…'}</div>}
    <footer className="bottom-area">
      {(notice||offline||connectionMessage)&&<p className="connection-note" role="status">{notice||(offline?'连接暂时断开，正在重连…':connectionMessage)}</p>}
      {state&&<Composer key={state.task_id} taskId={state.task_id} busy={state.state==='running'||state.state==='awaiting_user'||state.progress?.state==='running'} connected={!!status?.connected&&!!status?.logged_in&&!offline} onError={setNotice} onSend={send} onUpload={file=>uploadFile(state.task_id,file)} onStop={()=>action('stop',{target:stopTarget(state)}).catch(e=>setNotice(e.message))}/>}
    </footer>
    {panel==='history'&&<Dialog title="最近办的事" onClose={()=>setPanel(null)}><button className="primary-button" onClick={()=>void fresh()}><Icon name="plus"/>新办一件事</button><div className="history-list">{recent.filter(t=>t.title!=='新办一件事').map(t=><button key={t.task_id} onClick={()=>void choose(t.task_id)}>{t.title}</button>)}</div></Dialog>}
    {panel==='settings'&&<Dialog title="设置和帮助" onClose={()=>setPanel(null)}><fieldset className="profile-options"><legend>办事方式</legend>{[['normal','正常','Sol'],['low','低消耗','Terra']].map(([id,label,model])=><label className="option" key={id}><input type="radio" name="profile" checked={profile===id} disabled={!status?.models?.[id]} onChange={()=>{setProfile(id);localStorage.setItem('assistant-profile',id)}}/><span>{label}<small>{model}</small></span></label>)}</fieldset><p className="settings-note">下一件事开始使用。</p><a className="help-link" href="/help" target="_blank" rel="noreferrer">看看怎么用</a></Dialog>}
  </main>
}
