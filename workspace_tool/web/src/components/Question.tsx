import {useState} from 'react';
import type {Action} from '../state';
export function Question({value,onAction}:{value:any;onAction:Action}){
  const [answers,setAnswers]=useState<Record<string,string>>({}),[busy,setBusy]=useState(false),[error,setError]=useState('');
  async function reply(answer:any){setBusy(true);setError('');try{await onAction('answer',{native_request_id:value.request_id,answer})}catch(e){setError((e as Error).message);setBusy(false)}}
  const nativeQuestion=value.method?.endsWith('requestUserInput');
  const declineDecision=value.available_decisions?.includes('decline')?'decline':'cancel';
  return <section className="question" aria-label="需要您决定">
    {nativeQuestion?<form onSubmit={e=>{e.preventDefault();void reply({answers:Object.fromEntries(value.questions.map((q:any)=>[q.id,{answers:[answers[q.id]??'']}]))})}}>
      {value.questions.map((q:any)=><fieldset key={q.id}><legend>{q.question}</legend>{q.options?.map((o:any)=><label className="option" key={o.label}><input type="radio" name={q.id} checked={answers[q.id]===o.label} onChange={()=>setAnswers({...answers,[q.id]:o.label})}/><span>{o.label}</span></label>)}<input aria-label={q.question} placeholder="也可以直接说…" value={answers[q.id]??''} onChange={e=>setAnswers({...answers,[q.id]:e.target.value})}/></fieldset>)}
      <button className="primary-button" disabled={busy||value.questions.some((q:any)=>!answers[q.id]?.trim())}>确定</button>
    </form>:<><p>{value.question}</p>{(value.command||value.permissions)&&<details><summary>查看这一步</summary><pre>{value.command||JSON.stringify(value.permissions,null,2)}</pre></details>}
      <div className="dialog-actions"><button className="primary-button" disabled={busy} onClick={()=>void reply(value.method==='item/permissions/requestApproval'?{permissions:value.permissions??{},scope:'turn'}:{decision:'accept'})}>同意这一次</button><button disabled={busy} onClick={()=>void reply(value.method==='item/permissions/requestApproval'?{permissions:{},scope:'turn'}:{decision:declineDecision})}>先不要</button></div></>}
    {error&&<p className="error-text" role="alert">{error}</p>}
  </section>
}
