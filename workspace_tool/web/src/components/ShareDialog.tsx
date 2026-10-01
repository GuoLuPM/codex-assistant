import {useEffect,useState} from 'react';
import {api} from '../api';
import type {Action} from '../state';
import {Dialog} from './Dialog';
export function ShareDialog({taskId,sessionId,onAction,onClose}:{taskId:string;sessionId:string;onAction:Action;onClose:()=>void}){
  const [duration,setDuration]=useState('永久'),[state,setState]=useState<any>({status:'idle'}),[error,setError]=useState(''),[copied,setCopied]=useState(false);
  useEffect(()=>{let live=true;const read=()=>api(`/api/tasks/${taskId}/shares/${sessionId}`).then(s=>{if(live)setState(s)}).catch(()=>{});void read();const timer=setInterval(()=>void read(),1500);return()=>{live=false;clearInterval(timer)}},[taskId,sessionId]);
  const busy=['preparing','checking','starting','connecting'].includes(state.status);
  async function start(){try{setError('');let minutes:null|number=null;if(duration.trim()!=='永久'){const n=Number(duration);if(!Number.isInteger(n)||n<1||n>8760)throw new Error('请填 1—8760 小时，或选永久。');minutes=n*60}setState({status:'preparing'});setState(await onAction('share_start',{session_id:sessionId,minutes}))}catch(e){setError((e as Error).message);setState({status:'idle'})}}
  function step(delta:number){setDuration(String(Math.max(1,Math.min(8760,(duration==='永久'?24:Number(duration)||24)+delta))))}
  return <Dialog title="分享商品" onClose={onClose}>
    {state.status==='ready'?<><input className="share-url" aria-label="分享链接" readOnly value={state.url} onFocus={e=>e.target.select()}/><div className="dialog-actions"><button className="primary-button" onClick={()=>{void navigator.clipboard.writeText(state.url).then(()=>setCopied(true)).catch(()=>setError('请选中上面的链接复制。'))}}>{copied?'已复制':'复制链接'}</button><button className="quiet-button" onClick={()=>void onAction('share_stop',{session_id:sessionId}).then(setState).catch(e=>setError(e.message))}>停止分享</button></div></>:<><div className="duration-head"><button className="text-button" onClick={()=>setDuration('永久')} disabled={busy}>永久</button><label htmlFor="duration">有效时间（小时）</label></div><div className="duration-control"><button onClick={()=>step(-1)} aria-label="减少一小时" disabled={busy}>−</button><input id="duration" value={duration} disabled={busy} onChange={e=>setDuration(e.target.value)} onKeyDown={e=>{if(e.key==='ArrowUp'){e.preventDefault();step(1)}if(e.key==='ArrowDown'){e.preventDefault();step(-1)}}}/><button onClick={()=>step(1)} aria-label="增加一小时" disabled={busy}>＋</button></div><button className="primary-button" disabled={busy} onClick={()=>void start()}>{busy?'正在生成链接…':'确认分享'}</button></>}
    {(error||state.status==='failed')&&<p className="error-text" role="alert">{error||state.message}</p>}
    <p className="share-note">只读分享，电脑需开机联网。</p>
  </Dialog>
}
