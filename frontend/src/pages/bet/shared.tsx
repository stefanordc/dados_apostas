import { ReactNode, useEffect } from 'react'

export type Selection = {key:string;label:string;real_odds:boolean}
export type MarketDef = {key:string;label:string;period:'ft'|'ht';selections:Selection[]}
export type Field = {key:string;label:string;group:string}
export type Condition = {field:string;op:string;value?:number|string;other_field?:string}
export type Definition = {
 market:string;selection:string;side:'back'|'lay'
 entry:{minute_from:number;minute_to:number;scores:string[]}
 exit:{mode:string;minute:number|null;scores:string[]}
 conditions:Condition[]
 scope:{formato:string;countries:string[];competitions:string[];date_from:string|null;date_to:string|null}
 notes:string
}
export type Method = {id:number;nome:string;definicao:Definition}
export type Catalog = {cobertura:{ano:number;jogos:number}[];mercados:MarketDef[];campos:Field[];paises:string[];campeonatos:{pais:string;campeonato:string}[];
 saidas:Record<string,string>;operadores:string[]}

export const brl=(v:number|null|undefined)=>v==null?'—':v.toLocaleString('pt-BR',{style:'currency',currency:'BRL'})
export const num=(v:number|null|undefined,p=2)=>v==null?'—':v.toLocaleString('pt-BR',{minimumFractionDigits:p,maximumFractionDigits:p})
export const odd=(v:number|null|undefined)=>v==null?'—':v.toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2})
export const dateBr=(iso?:string|null)=>iso?iso.slice(0,10).split('-').reverse().join('/'):'—'
export const plClass=(v:number|null|undefined)=>v==null||v===0?'':v>0?'bf-pos':'bf-neg'

export function Modal({title,onClose,children,wide}:{title:string;onClose:()=>void;children:ReactNode;wide?:boolean}) {
 useEffect(()=>{
  const onKey=(e:KeyboardEvent)=>{if(e.key==='Escape')onClose()}
  window.addEventListener('keydown',onKey);return()=>window.removeEventListener('keydown',onKey)
 },[onClose])
 return <div className="bf-modal-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget)onClose()}}>
  <div className={`bf-modal${wide?' wide':''}`} role="dialog" aria-modal="true" aria-label={title}>
   <header><h3>{title}</h3><button type="button" onClick={onClose} aria-label="Fechar">×</button></header>
   <div className="bf-modal-body">{children}</div>
  </div></div>
}

export function LineChart({points,height=190,format=brl,baseline}:{points:{label:string;value:number}[];height?:number;format?:(v:number)=>string;baseline?:number}) {
 if(points.length<2)return <p className="bf-muted">Dados insuficientes para o gráfico.</p>
 const W=900,H=height,padL=70,padR=14,padT=12,padB=26
 const vals=points.map(p=>p.value).concat(baseline!=null?[baseline]:[])
 let min=Math.min(...vals),max=Math.max(...vals)
 if(min===max){min-=1;max+=1}
 const x=(i:number)=>padL+i*(W-padL-padR)/(points.length-1)
 const y=(v:number)=>padT+(max-v)*(H-padT-padB)/(max-min)
 const path=points.map((p,i)=>`${i?'L':'M'}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(' ')
 const ticks=[min,(min+max)/2,max]
 const last=points[points.length-1].value,first=points[0].value
 return <svg className="bf-chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Evolução">
  {ticks.map((t,i)=><g key={i}><line x1={padL} x2={W-padR} y1={y(t)} y2={y(t)} className="grid"/><text x={padL-8} y={y(t)+4} textAnchor="end">{format(t)}</text></g>)}
  {baseline!=null&&<line x1={padL} x2={W-padR} y1={y(baseline)} y2={y(baseline)} className="base"/>}
  <path d={path} className={last>=first?'line up':'line down'} fill="none"/>
  <text x={padL} y={H-6}>{points[0].label}</text><text x={W-padR} y={H-6} textAnchor="end">{points[points.length-1].label}</text>
 </svg>
}

export function Stat({label,value,tone,hint}:{label:string;value:ReactNode;tone?:string;hint?:string}) {
 return <div className="bf-stat" title={hint}><small>{label}</small><strong className={tone}>{value}</strong></div>
}
