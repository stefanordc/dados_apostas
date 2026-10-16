import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, query } from '../../api'
import { Stat } from './shared'

type Candidate={padrao:string;evidencia:number;parcial:number;confianca:'alta'|'media'|'baixa';fonte_referencia:string;similaridade:number}
type Example={data:string;jogo_fonte:string;jogo_outra:string;fonte_outra:string}
type Suggestion={pais:string;fonte:string;nome_fonte:string;candidatos:Candidate[];exemplos:Example[];confianca:'alta'|'media'|'baixa'}
type Saved={pais:string;fonte:string;nome_fonte:string;nome_padrao:string|null;status:string}
type Imported={pais:string;liga:string;temporada:string;jogos:number;de:string;ate:string}
type Data={cobertura:{jogos_total:number;com_odds_reais:number;sem_odds:number;por_fonte:Record<string,number>;jogos_unicos:number};
 sugestoes:Suggestion[];total_sugestoes:number;vinculos:Saved[];paises:string[]}

const SRC:Record<string,string>={jogos:'jogos',odds:'odds',historico_odds:'historico_odds',api:'API'}
const CONF:Record<string,string>={alta:'Alta confiança',media:'Média confiança',baixa:'Baixa confiança'}
const CUSTOM='__custom__'
const keyOf=(s:Pick<Suggestion,'pais'|'fonte'|'nome_fonte'>)=>`${s.pais}|${s.fonte}|${s.nome_fonte}`

export default function Conciliacao({onChange}:{onChange?:()=>void}) {
 const [data,setData]=useState<Data|null>(null)
 const [country,setCountry]=useState('')
 const [error,setError]=useState('')
 const [busyApi,setBusyApi]=useState(false)
 const [pending,setPending]=useState(0)
 const [imported,setImported]=useState<Imported[]>([])
 const [apiForm,setApiForm]=useState({pais:'england',liga:'premier-league',temporada:'2023-2024'})
 const [apiMsg,setApiMsg]=useState<{kind:'ok'|'err';text:string}|null>(null)
 const [choice,setChoice]=useState<Record<string,string>>({})
 const [custom,setCustom]=useState<Record<string,string>>({})
 const refreshTimer=useRef<ReturnType<typeof setTimeout>|null>(null)
 const inflight=useRef(0)
 const load=useCallback(()=>api<Data>(`/api/bet/conciliacao?${query({pais:country})}`).then(d=>{setData(d);setError('')}).catch((e:Error)=>setError(e.message)),[country])
 useEffect(()=>{setData(null);load()},[load])
 const loadImported=useCallback(()=>api<Imported[]>('/api/bet/api/importados').then(setImported).catch(()=>setImported([])),[])
 useEffect(()=>{loadImported()},[loadImported])
 useEffect(()=>()=>{if(refreshTimer.current)clearTimeout(refreshTimer.current)},[])

 const scheduleRefresh=useCallback(()=>{
  if(refreshTimer.current)clearTimeout(refreshTimer.current)
  refreshTimer.current=setTimeout(()=>{
   if(inflight.current>0){scheduleRefresh();return}
   load().then(()=>onChange?.()).catch(()=>{})
  },600)
 },[load,onChange])

 const beginBg=()=>{inflight.current+=1;setPending(n=>n+1)}
 const endBg=()=>{inflight.current=Math.max(0,inflight.current-1);setPending(n=>Math.max(0,n-1));scheduleRefresh()}

 const importApi=async()=>{
  setBusyApi(true);setApiMsg(null)
  try{
   const r=await api<{jogos:number;com_minutos:number;de:string;ate:string}>('/api/bet/api/importar',{method:'POST',body:JSON.stringify(apiForm)})
   setApiMsg({kind:'ok',text:`${r.jogos} jogos importados (${r.com_minutos} com minutos dos gols), de ${r.de.split('-').reverse().join('/')} a ${r.ate.split('-').reverse().join('/')}.`})
   await loadImported();setData(null);await load();onChange?.()
  }catch(e:any){setApiMsg({kind:'err',text:e.message})}finally{setBusyApi(false)}
 }
 const removeApi=async(i:Imported)=>{
  try{await api(`/api/bet/api/importados?${query({pais:i.pais,liga:i.liga,temporada:i.temporada})}`,{method:'DELETE'});await loadImported();setData(null);await load();onChange?.()}
  catch(e:any){setApiMsg({kind:'err',text:e.message})}
 }

 const pickedName=(s:Suggestion)=>{
  const k=keyOf(s),sel=choice[k]??s.candidatos[0].padrao
  return sel===CUSTOM?(custom[k]||'').trim():sel
 }
 const applyLocal=(s:Suggestion,status:'vinculado'|'ignorado',padrao:string|null)=>{
  setData(d=>{
   if(!d)return d
   const k=keyOf(s)
   const sugestoes=d.sugestoes.filter(x=>keyOf(x)!==k)
   const vinculo:Saved={pais:s.pais,fonte:s.fonte,nome_fonte:s.nome_fonte,nome_padrao:padrao,status}
   const vinculos=[vinculo,...d.vinculos.filter(v=>!(v.pais===s.pais&&v.fonte===s.fonte&&v.nome_fonte===s.nome_fonte))]
   return {...d,sugestoes,total_sugestoes:Math.max(0,d.total_sugestoes-1),vinculos}
  })
  setChoice(o=>{const n={...o};delete n[keyOf(s)];return n})
  setCustom(o=>{const n={...o};delete n[keyOf(s)];return n})
 }
 const restoreLocal=(s:Suggestion)=>{
  setData(d=>{
   if(!d)return d
   if(d.sugestoes.some(x=>keyOf(x)===keyOf(s)))return d
   return {...d,sugestoes:[s,...d.sugestoes],total_sugestoes:d.total_sugestoes+1,
    vinculos:d.vinculos.filter(v=>!(v.pais===s.pais&&v.fonte===s.fonte&&v.nome_fonte===s.nome_fonte))}
  })
 }
 const postLink=async(s:Suggestion,status:'vinculado'|'ignorado',padrao:string|null,ref?:Candidate)=>{
  await api('/api/bet/conciliacao/vinculo',{method:'POST',body:JSON.stringify({pais:s.pais,fonte:s.fonte,nome_fonte:s.nome_fonte,nome_padrao:padrao,status})})
  if(status==='vinculado'&&padrao&&ref&&ref.padrao!==padrao){
   await api('/api/bet/conciliacao/vinculo',{method:'POST',body:JSON.stringify({pais:s.pais,fonte:ref.fonte_referencia,nome_fonte:ref.padrao,nome_padrao:padrao,status:'vinculado'})})
  }
 }
 const link=(s:Suggestion,status:'vinculado'|'ignorado')=>{
  const k=keyOf(s),padrao=status==='vinculado'?pickedName(s):null
  if(status==='vinculado'&&!padrao){setError('Informe o nome padrão do clube.');return}
  const ref=status==='vinculado'?(s.candidatos.find(c=>choice[k]===undefined?c===s.candidatos[0]:c.padrao===choice[k])??s.candidatos[0]):undefined
  setError('')
  applyLocal(s,status,padrao)
  beginBg()
  postLink(s,status,padrao,ref).catch((e:Error)=>{restoreLocal(s);setError(e.message)}).finally(endBg)
 }
 const linkAllHigh=()=>{
  const high=(data?.sugestoes??[]).filter(s=>s.confianca==='alta')
  if(!high.length||!window.confirm(`Vincular ${high.length} clubes de alta confiança usando o nome sugerido como padrão?`))return
  setError('')
  for(const s of high){
   const padrao=s.candidatos[0].padrao
   applyLocal(s,'vinculado',padrao)
   beginBg()
   postLink(s,'vinculado',padrao,s.candidatos[0]).catch((e:Error)=>{restoreLocal(s);setError(e.message)}).finally(endBg)
  }
 }
 const remove=(v:Saved)=>{
  setData(d=>d?{...d,vinculos:d.vinculos.filter(x=>!(x.pais===v.pais&&x.fonte===v.fonte&&x.nome_fonte===v.nome_fonte))}:d)
  beginBg()
  api(`/api/bet/conciliacao/vinculo?${query({pais:v.pais,fonte:v.fonte,nome_fonte:v.nome_fonte})}`,{method:'DELETE'})
   .catch((e:Error)=>{setData(d=>d?{...d,vinculos:[v,...d.vinculos]}:d);setError(e.message)})
   .finally(endBg)
 }
 const sugestoes=data?.sugestoes??[]
 const highCount=useMemo(()=>sugestoes.filter(s=>s.confianca==='alta').length,[sugestoes])
 if(!data)return <section className="bf-main full">{error?<p className="bf-alert err" role="alert">{error}</p>:<p className="bf-muted pad">Comparando clubes entre as tabelas jogos, odds e historico_odds...</p>}</section>
 const cov=data.cobertura
 return <section className="bf-main full">
  <h2 className="bf-h2">Conciliação de clubes</h2>
  <p className="bf-hint">Os jogos vêm da tabela <b>jogos</b>; as odds reais, da tabela <b>odds</b> e, na falta dela, da <b>historico_odds</b>. Quando o mesmo jogo aparece com nomes de clube diferentes, ele só é unido depois que você confirma o vínculo e escolhe o nome padrão. Os vínculos ficam salvos para sempre.</p>
  <div className="bf-stats">
   <Stat label="Jogos na tabela jogos" value={cov.jogos_total}/>
   <Stat label="Com odds reais" value={cov.com_odds_reais} tone="bf-pos" hint={Object.entries(cov.por_fonte).map(([k,v])=>`${k}: ${v}`).join(' · ')}/>
   <Stat label="Sem odds (estimadas)" value={cov.sem_odds}/>
   <Stat label="Vínculos pendentes" value={data.total_sugestoes} tone={data.total_sugestoes?'bf-neg':'bf-pos'}/>
   <Stat label="Vínculos salvos" value={data.vinculos.length}/>
  </div>
  {error&&<p className="bf-alert err" role="alert">{error}</p>}
  {pending>0&&<p className="bf-alert info" role="status">Salvando {pending} vínculo{pending>1?'s':''} em segundo plano…</p>}
  <div className="bf-form inline">
   <label>País<select value={country} onChange={e=>setCountry(e.target.value)}><option value="">Todos</option>{data.paises.map(p=><option key={p}>{p}</option>)}</select></label>
   <button type="button" className="bf-btn" disabled={!highCount} onClick={linkAllHigh}>Vincular todos de alta confiança ({highCount})</button>
   <button type="button" className="bf-btn" onClick={()=>{setData(null);load()}}>Atualizar</button>
  </div>
  <h3 className="bf-h3">Odds da API futpythontrader (3ª fonte)</h3>
  <p className="bf-hint">Use quando os jogos não têm odds nas tabelas. Informe país, liga e temporada exatamente como no catálogo da API (ex.: <code>england</code> / <code>premier-league</code> / <code>2023-2024</code>; Brasil usa só o ano: <code>brazil</code> / <code>serie-a-betano</code> / <code>2026</code>). As odds importadas incluem Correct Score, 1º tempo e minutos dos gols.</p>
  <div className="bf-form inline">
   <label>País (slug)<input value={apiForm.pais} onChange={e=>setApiForm(f=>({...f,pais:e.target.value}))}/></label>
   <label>Liga (slug)<input value={apiForm.liga} onChange={e=>setApiForm(f=>({...f,liga:e.target.value}))}/></label>
   <label>Temporada<input value={apiForm.temporada} onChange={e=>setApiForm(f=>({...f,temporada:e.target.value}))}/></label>
   <button type="button" className="bf-btn primary" disabled={busyApi} onClick={importApi}>{busyApi?'Importando...':'Importar da API'}</button>
  </div>
  {apiMsg&&<p className={`bf-alert ${apiMsg.kind}`} role={apiMsg.kind==='err'?'alert':'status'}>{apiMsg.text}</p>}
  {imported.length>0&&<div className="bf-tablewrap"><table className="bf-table dense"><thead><tr><th>País</th><th>Liga</th><th>Temporada</th><th>Jogos</th><th>Período</th><th></th></tr></thead><tbody>
   {imported.map(i=><tr key={`${i.pais}${i.liga}${i.temporada}`}><td>{i.pais}</td><td>{i.liga}</td><td>{i.temporada}</td><td>{i.jogos}</td><td>{i.de.split('-').reverse().join('/')} a {i.ate.split('-').reverse().join('/')}</td>
    <td><button type="button" className="bf-btn small" onClick={()=>removeApi(i)}>Remover</button></td></tr>)}</tbody></table></div>}
  <h3 className="bf-h3">Pendentes de conferência</h3>
  {!sugestoes.length?<p className="bf-alert ok">Nenhum clube pendente{country?` em ${country}`:''}. Todos os nomes com jogo na mesma data foram unidos.</p>:
   <div className="bf-tablewrap tall"><table className="bf-table recon"><thead><tr><th>País</th><th>Clube na fonte</th><th>É o mesmo que… (nome padrão)</th><th>Evidência</th><th></th></tr></thead><tbody>
    {sugestoes.map(s=>{
     const k=keyOf(s),sel=choice[k]??s.candidatos[0].padrao
     return <tr key={k}>
      <td>{s.pais}</td>
      <td><strong>{s.nome_fonte}</strong><small className="bf-muted"> {SRC[s.fonte]}</small></td>
      <td>
       {s.candidatos.map(c=><label key={c.padrao} className="bf-radio"><input type="radio" name={k} checked={sel===c.padrao} onChange={()=>setChoice(o=>({...o,[k]:c.padrao}))}/>
        {c.padrao} <span className={`bf-tag ${c.confianca==='alta'?'ok':'warn'}`}>{CONF[c.confianca]}</span> <small className="bf-muted">{c.evidencia} jogo(s){c.parcial?' · outro time idêntico':''}</small></label>)}
       <label className="bf-radio"><input type="radio" name={k} checked={sel===CUSTOM} onChange={()=>setChoice(o=>({...o,[k]:CUSTOM}))}/>Outro nome padrão:
        <input className="bf-inline-input" value={custom[k]||''} onFocus={()=>setChoice(o=>({...o,[k]:CUSTOM}))} onChange={e=>setCustom(o=>({...o,[k]:e.target.value}))} placeholder="Digite o nome"/></label>
      </td>
      <td className="ex">{s.exemplos.slice(0,2).map((x,i)=><div key={i}><small>{x.data.split('-').reverse().join('/')} · {x.jogo_fonte} ↔ {x.jogo_outra} ({x.fonte_outra})</small></div>)}</td>
      <td className="act"><button type="button" className="bf-btn small primary" onClick={()=>link(s,'vinculado')}>Vincular</button>
       <button type="button" className="bf-btn small" onClick={()=>link(s,'ignorado')} title="Não são o mesmo clube: não sugerir novamente">Ignorar</button></td></tr>})}
   </tbody></table></div>}
  {data.total_sugestoes>sugestoes.length&&<p className="bf-hint">Mostrando as {sugestoes.length} primeiras de {data.total_sugestoes}. Filtre por país para ver as demais.</p>}
  <h3 className="bf-h3">Vínculos salvos</h3>
  {!data.vinculos.length?<p className="bf-muted">Nenhum vínculo salvo ainda.</p>:<div className="bf-tablewrap tall"><table className="bf-table dense"><thead><tr><th>País</th><th>Fonte</th><th>Nome na fonte</th><th>Nome padrão</th><th>Situação</th><th></th></tr></thead><tbody>
   {data.vinculos.map(v=><tr key={`${v.pais}|${v.fonte}|${v.nome_fonte}`}><td>{v.pais}</td><td>{v.fonte}</td><td>{v.nome_fonte}</td><td>{v.nome_padrao??'—'}</td><td>{v.status==='ignorado'?'Ignorado':'Vinculado'}</td>
    <td><button type="button" className="bf-btn small" onClick={()=>remove(v)}>Remover</button></td></tr>)}</tbody></table></div>}
 </section>
}
