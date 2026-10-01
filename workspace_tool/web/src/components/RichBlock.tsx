import {memo} from 'react';
import type {Action,Block,Selection} from '../state';
import {ProductPicker,Comparison} from './ProductPicker';
import {Icon} from './Icon';
export const RichBlock=memo(function RichBlock({block,taskId,onAction}:{block:Block;taskId:string;onAction:Action}){
  if(block.kind==='text')return <div className={'message '+(block.body.role==='user'?'user':'assistant')}><p>{block.body.text}</p></div>;
  if(block.kind==='products')return <ProductPicker taskId={taskId} value={block.body as Selection} onAction={onAction}/>;
  if(block.kind==='comparison')return <Comparison items={block.body.items}/>;
  if(block.kind==='artifact')return <div className="artifact"><Icon name="file"/><div><strong>{block.body.display_name}</strong></div><a className="primary-button" href={block.body.url} download><Icon name="download"/>保存</a></div>;
  return null;
});
