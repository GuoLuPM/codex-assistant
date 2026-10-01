import {memo,useEffect,useRef,useState} from 'react';
import type {Action,Product,Selection} from '../state';
import {Icon} from './Icon';
import {ShareDialog} from './ShareDialog';
const same=(a:string[],b:string[])=>a.length===b.length&&a.every((x,i)=>x===b[i]);
const ProductCard=memo(function ProductCard({product,checked,expanded,disabled,toggle,expand}:{product:Product;checked:boolean;expanded:boolean;disabled:boolean;toggle:(id:string)=>void;expand:(id:string)=>void}){
  return <article className={'product-card'+(checked?' selected':'')}>
    <label className="product-choice"><input type="checkbox" checked={checked} disabled={disabled} onChange={()=>toggle(product.id)} aria-label={'选择 '+product.name}/>
      <div className="product-core">{product.image_url&&<img src={product.image_url} alt="" loading="lazy"/>}<div className="product-copy"><h3>{product.name}</h3>{[product.model,product.variant].filter(v=>v&&!product.name.includes(v)).map(v=><p className="product-variant" key={v}>{v}</p>)}
        <div className="prices">{product.prices.map((p,i)=><p key={i}><span>{p.label}</span><strong>{p.value}<span className="currency">元</span></strong></p>)}</div>
      </div></div>
    </label>
    <details open={expanded} onToggle={e=>{if(e.currentTarget.open!==expanded)expand(product.id)}}><summary onClick={e=>{e.preventDefault();expand(product.id)}}>详情<Icon name="chevron"/></summary><div className="product-detail">{product.features&&<p>{product.features}</p>}{product.source_file&&<p className="source">资料：{product.source_file}{product.locator?' · '+product.locator:''}</p>}</div></details>
  </article>
});
export function Comparison({items}:{items:Product[]}){return <div className="comparison" tabIndex={0} aria-label="商品对比"><table><thead><tr>{items.map(p=><th key={p.id}>{p.name}</th>)}</tr></thead><tbody><tr>{items.map(p=><td key={p.id}>{p.prices.map((v,i)=><div key={i}>{v.label} {v.value}元</div>)}</td>)}</tr><tr>{items.map(p=><td key={p.id}>{p.features||'资料里没写'}</td>)}</tr></tbody></table></div>}
export function ProductPicker({taskId,value,onAction}:{taskId:string;value:Selection;onAction:Action}){
  const [selected,setSelected]=useState(value.selected_ids),[expanded,setExpanded]=useState<Set<string>>(new Set()),[error,setError]=useState('');
  const [saving,setSaving]=useState(false),[exporting,setExporting]=useState(value.export_state==='running'),[share,setShare]=useState(false),[compare,setCompare]=useState(false);
  const desired=useRef(value.selected_ids),saved=useRef(value.selected_ids),revision=useRef(value.revision),worker=useRef<Promise<void>|null>(null),actions=useRef(onAction);
  actions.current=onAction;
  useEffect(()=>{if(value.export_state==='completed'||value.export_state==='failed')setExporting(false)},[value.export_state]);
  useEffect(()=>{if(value.revision>=revision.current&&!worker.current){revision.current=value.revision;saved.current=value.selected_ids;desired.current=value.selected_ids;setSelected(value.selected_ids)}},[value.revision,value.selected_ids]);
  async function flush(){
    if(worker.current)return worker.current;
    const pending=(async()=>{await Promise.resolve();setSaving(true);setError('');try{
      while(!same(desired.current,saved.current)){
        const target=[...desired.current];
        const next=await actions.current('select',{session_id:value.session_id,ids:target,revision:revision.current});
        revision.current=next.revision;saved.current=next.selected_ids;
      }
    }catch(e){setError('这次勾选还没保存。'+(e as Error).message);throw e}finally{setSaving(false);worker.current=null}})();
    worker.current=pending;return pending;
  }
  const toggle=(id:string)=>{if(exporting)return;const next=desired.current.includes(id)?desired.current.filter(x=>x!==id):[...desired.current,id];desired.current=next;setSelected(next);void flush().catch(()=>{})};
  const expand=(id:string)=>setExpanded(old=>{const next=new Set(old);next.has(id)?next.delete(id):next.add(id);return next});
  async function exportPpt(){if(exporting)return;setExporting(true);setError('');try{await flush();await onAction('export',{session_id:value.session_id,revision:revision.current})}catch(e){setError((e as Error).message);setExporting(false)}}
  const all=expanded.size===value.items.length;
  return <section className="product-picker" aria-label={value.title}>
    <div className="picker-heading"><h2>{value.title}</h2><button className="icon-button" aria-label="分享商品" onClick={()=>setShare(true)}><Icon name="share"/></button></div>
    <div className="picker-toolbar"><span>已选 {selected.length} 款</span><button className="text-button" onClick={()=>setExpanded(all?new Set():new Set(value.items.map(p=>p.id)))}>{all?'全部收起':'全部展开'}</button></div>
    <div className="product-grid">{value.items.map(product=><ProductCard key={product.id} product={product} checked={selected.includes(product.id)} expanded={expanded.has(product.id)} disabled={value.state!=='open'||exporting} toggle={toggle} expand={expand}/>)}</div>
    {error&&<div className="inline-error" role="alert"><p>{error}</p><button onClick={()=>void flush().catch(()=>{})}>重试保存</button></div>}
    {compare&&<Comparison items={value.items.filter(p=>selected.includes(p.id))}/>}
    <div className="picker-actions">{selected.length>=2&&selected.length<=4&&<button className="quiet-button" onClick={()=>setCompare(!compare)}>{compare?'收起对比':'对比一下'}</button>}{value.export_state!=='completed'&&<button className="primary-button" disabled={!selected.length||exporting||!!error} onClick={()=>void exportPpt()}>{exporting?'正在做成图册…':'做成图册'}</button>}</div>
    {share&&<ShareDialog taskId={taskId} sessionId={value.session_id} onAction={onAction} onClose={()=>setShare(false)}/>}
    <span className="sr-only" role="status">{saving?'正在保存选择':''}</span>
  </section>
}
