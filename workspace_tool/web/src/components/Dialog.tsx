import {useEffect,useRef,type ReactNode} from 'react';
import {Icon} from './Icon';
export function Dialog({title,onClose,children}:{title:string;onClose:()=>void;children:ReactNode}){
  const ref=useRef<HTMLDialogElement>(null);
  useEffect(()=>{ref.current?.showModal();const d=ref.current;return()=>d?.close()},[]);
  return <dialog ref={ref} className="dialog" onCancel={onClose} onClick={e=>{if(e.target===e.currentTarget){const r=e.currentTarget.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)onClose()}}}><div className="dialog-head"><h2>{title}</h2><button className="icon-button" aria-label="关闭" onClick={onClose}><Icon name="close"/></button></div>{children}</dialog>
}
