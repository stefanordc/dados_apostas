import { useEffect, useMemo, useState } from 'react'
import { api } from '../../api'
import { Catalog, Condition, Definition, Method } from './shared'

const EMPTY:Definition={market:'match_odds',selection:'home',side:'back',
 entry:{minute_from:0,minute_to:0,scores:['0-0']},exit:{mode:'never',minute:null,scores:[]},conditions:[],
 scope:{formato:'',countries:[],competitions:[],date_from:null,date_to:null},notes:''}
const clone=<T,>(v:T):T=>JSON.parse(JSON.stringify(v))
const parseScores=(s:string)=>s.split(/[,;\s]+/).map(x=>x.trim().replace(/x/gi,'-')).filter(Boolean)

export default function Metodos({catalog,methods,reload}:{catalog:Catalog;methods:Method[];reload:()=>Promise<unknown>|void}) {
 const [selectedId,setSelectedId]=useState<number|null>(null)
 const [name,setName]=useState('')
 const [def,setDef]=useState<Definition>(clone(EMPTY))
 const [entryScores,setEntryScores]=useState('0-0')
 const [exitScores,setExitScores]=useState('')
 const [msg,setMsg]=useState<{kind:'ok'|'err';text:string}|null>(null)
 const [saving,setSaving]=useState(false)
 const [started,setStarted]=useState(false)
 const market=catalog.mercados.find(m=>m.key===def.market)
 const fieldGroups=useMemo(()=>{
  const groups:Record<string,typeof catalog.campos>={}
  catalog.campos.forEach(f=>{(groups[f.group]??=[]).push(f)})
  return groups
 },[catalog])
 const competitionOptions=catalog.campeonatos.filter(c=>!def.scope.countries.length||def.scope.countries.includes(c.pais))
 const load=(m:Method|null)=>{
  setMsg(null)
  if(!m){setSelectedId(null);setName('');setDef(clone(EMPTY));setEntryScores('0-0');setExitScores('');return}
  setSelectedId(m.id);setName(m.nome);setDef(clone(m.definicao))
  setEntryScores(m.definicao.entry.scores.join(', '));setExitScores(m.definicao.exit.scores.join(', '))
 }
 useEffect(()=>{
  if(!started&&methods.length){setStarted(true);load(methods[0])}
 },[methods,started])
 const patch=(p:Partial<Definition>)=>setDef(d=>({...d,...p}))
 const setCond=(i:number,p:Partial<Condition>)=>setDef(d=>({...d,conditions:d.conditions.map((c,k)=>k===i?{...c,...p}:c)}))
 const save=async(asNew=false)=>{
  setSaving(true);setMsg(null)
  const body={nome:name,definicao:{...def,entry:{...def.entry,scores:parseScores(entryScores)},
   exit:{...def.exit,scores:parseScores(exitScores)}}}
  try{
   const saved=await api<Method>(asNew||!selectedId?'/api/bet/metodos':`/api/bet/metodos/${selectedId}`,
    {method:asNew||!selectedId?'POST':'PUT',body:JSON.stringify(body)})
   await reload();load(saved);setMsg({kind:'ok',text:'Método salvo.'})
  }catch(e:any){setMsg({kind:'err',text:e.message})}finally{setSaving(false)}
 }
 const remove=async()=>{
  if(!selectedId||!window.confirm(`Excluir o método "${name}"?`))return
  try{await api(`/api/bet/metodos/${selectedId}`,{method:'DELETE'});await reload();load(null)}
  catch(e:any){setMsg({kind:'err',text:e.message})}
 }
 const FieldOptions=()=><>{Object.entries(fieldGroups).map(([g,list])=><optgroup key={g} label={g}>{list.map(f=><option key={f.key} value={f.key}>{f.label}</option>)}</optgroup>)}</>
 return <div className="bf-split">
  <aside className="bf-side">
   <div className="bf-side-head">Meus métodos<button type="button" className="bf-btn small" onClick={()=>load(null)}>+ Novo</button></div>
   <ul className="bf-list">{methods.map(m=><li key={m.id}><button type="button" className={m.id===selectedId?'on':''} onClick={()=>load(m)}>
    <strong>{m.nome}</strong>
    <small>{m.definicao.side==='lay'?'Lay':'Back'} · {catalog.mercados.find(x=>x.key===m.definicao.market)?.label}</small></button></li>)}
    {!methods.length&&<li className="bf-muted pad">Nenhum método salvo.</li>}</ul>
  </aside>
  <section className="bf-main">
   <h2 className="bf-h2">{selectedId?'Editar método':'Novo método'}</h2>
   <div className="bf-form">
    <label className="wide">Nome do método<input value={name} onChange={e=>setName(e.target.value)} placeholder="Ex.: Vovô da casa"/></label>
    <fieldset><legend>Mercado e entrada</legend>
     <label>Mercado<select value={def.market} onChange={e=>{const m=catalog.mercados.find(x=>x.key===e.target.value)!;patch({market:m.key,selection:m.selections[0].key})}}>
      {catalog.mercados.map(m=><option key={m.key} value={m.key}>{m.label}</option>)}</select></label>
     <label>Seleção<select value={def.selection} onChange={e=>patch({selection:e.target.value})}>
      {market?.selections.map(s=><option key={s.key} value={s.key}>{s.label}</option>)}</select></label>
     <div className="bf-seg" role="group" aria-label="Tipo da entrada">
      <button type="button" className={def.side==='back'?'back on':'back'} onClick={()=>patch({side:'back'})}>Back (a favor)</button>
      <button type="button" className={def.side==='lay'?'lay on':'lay'} onClick={()=>patch({side:'lay'})}>Lay (contra)</button></div>
     <label>Minuto da entrada · de<input type="number" min={0} max={90} value={def.entry.minute_from} onChange={e=>patch({entry:{...def.entry,minute_from:Number(e.target.value)}})}/></label>
     <label>até<input type="number" min={0} max={90} value={def.entry.minute_to} onChange={e=>patch({entry:{...def.entry,minute_to:Number(e.target.value)}})}/></label>
     <label className="wide">Placares de entrada (mandante-visitante, separados por vírgula)<input value={entryScores} onChange={e=>setEntryScores(e.target.value)} placeholder="1-0, 2-1 (vazio = qualquer placar)"/></label>
    </fieldset>
    <fieldset><legend>Saída</legend>
     <label>Quando sair<select value={def.exit.mode} onChange={e=>patch({exit:{...def.exit,mode:e.target.value}})}>
      {Object.entries(catalog.saidas).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></label>
     {def.exit.mode==='minute'&&<><label>Minuto da saída<input type="number" min={1} max={90} value={def.exit.minute??''} onChange={e=>patch({exit:{...def.exit,minute:e.target.value===''?null:Number(e.target.value)}})}/></label>
      <label className="wide">Sair somente se o placar for (vazio = qualquer)<input value={exitScores} onChange={e=>setExitScores(e.target.value)} placeholder="0-0, 0-1"/></label></>}
     <p className="bf-hint wide">Sem saída, a posição é mantida até o apito final. A saída fecha a posição com odds estimadas pelo modelo.</p>
    </fieldset>
    <fieldset><legend>Condições (estatísticas e odds)</legend>
     {def.conditions.map((c,i)=><div className="bf-cond wide" key={i}>
      <select aria-label="Estatística" value={c.field} onChange={e=>setCond(i,{field:e.target.value})}><FieldOptions/></select>
      <select aria-label="Operador" value={c.op} onChange={e=>setCond(i,{op:e.target.value})}>{catalog.operadores.map(o=><option key={o}>{o}</option>)}</select>
      <select aria-label="Comparar com" value={c.other_field?'field':'value'} onChange={e=>setCond(i,e.target.value==='field'?{other_field:catalog.campos[0].key,value:undefined}:{other_field:undefined,value:0})}>
       <option value="value">valor</option><option value="field">outra estatística</option></select>
      {c.other_field?<select aria-label="Outra estatística" value={c.other_field} onChange={e=>setCond(i,{other_field:e.target.value})}><FieldOptions/></select>
       :<input type="number" step="any" aria-label="Valor" value={c.value??''} onChange={e=>setCond(i,{value:e.target.value})}/>}
      <button type="button" className="bf-x" aria-label="Remover condição" onClick={()=>setDef(d=>({...d,conditions:d.conditions.filter((_,k)=>k!==i)}))}>×</button></div>)}
     <button type="button" className="bf-btn small wide-btn" onClick={()=>setDef(d=>({...d,conditions:[...d.conditions,{field:'odd_casa_ft',op:'<',value:1.8}]}))}>+ Adicionar condição</button>
     <p className="bf-hint wide">Exemplos: odd do mandante &lt; 1,80 · odd do mandante &lt; outra estatística “odd do visitante” · média de gols do mandante ≥ 1,5.</p>
    </fieldset>
    <fieldset><legend>Escopo do teste</legend>
     <label>Formato<select value={def.scope.formato} onChange={e=>patch({scope:{...def.scope,formato:e.target.value}})}><option value="">Liga e Copa</option><option>Liga</option><option>Copa</option></select></label>
     <label>Data inicial<input type="date" value={def.scope.date_from??''} onChange={e=>patch({scope:{...def.scope,date_from:e.target.value||null}})}/></label>
     <label>Data final<input type="date" value={def.scope.date_to??''} onChange={e=>patch({scope:{...def.scope,date_to:e.target.value||null}})}/></label>
     <label className="wide">Países (vazio = todos; Ctrl para vários)<select multiple size={5} value={def.scope.countries} onChange={e=>patch({scope:{...def.scope,countries:Array.from(e.target.selectedOptions).map(o=>o.value)}})}>
      {catalog.paises.map(p=><option key={p}>{p}</option>)}</select></label>
     <label className="wide">Campeonatos (vazio = todos)<select multiple size={5} value={def.scope.competitions} onChange={e=>patch({scope:{...def.scope,competitions:Array.from(e.target.selectedOptions).map(o=>o.value)}})}>
      {[...new Set(competitionOptions.map(c=>c.campeonato))].map(c=><option key={c}>{c}</option>)}</select></label>
    </fieldset>
    <label className="wide">Observações<textarea rows={2} value={def.notes} onChange={e=>patch({notes:e.target.value})}/></label>
   </div>
   {msg&&<p className={`bf-alert ${msg.kind}`} role={msg.kind==='err'?'alert':'status'}>{msg.text}</p>}
   <div className="bf-actions">
    <button type="button" className="bf-btn primary" disabled={saving} onClick={()=>save(false)}>{saving?'Salvando...':'Salvar método'}</button>
    {selectedId&&<button type="button" className="bf-btn" disabled={saving} onClick={()=>save(true)}>Salvar como novo</button>}
    {selectedId&&<button type="button" className="bf-btn danger" onClick={remove}>Excluir</button>}
   </div>
  </section>
 </div>
}
