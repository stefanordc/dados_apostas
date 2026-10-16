import { useEffect, useMemo, useState } from 'react'
import { api } from '../../api'
import { LineChart, Stat, brl, dateBr, num, odd, plClass } from './shared'

type Bet={id:number;data_jogo:string;jogo:string;pais:string;campeonato:string;mercado_nome:string;selecao_nome:string;lado:string;odd:number;
 stake:number;minuto:number;placar_entrada:string;odd_origem:string;placar_final:string;resultado:string;lucro:number;criado_em:string}
type Report={config:{banca_inicial:number;banca_atual:number};apostas:Bet[];meses:{mes:string;lucro:number;apostas:number;green:number;red:number;banca:number}[];
 curva:{ordem:number;banca:number;data:string|null}[];totais:{apostas:number;lucro:number;green:number;red:number;stake_total:number;roi_stake:number|null}}

const monthLabel=(m:string)=>{const [y,mo]=m.split('-');return `${['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez'][Number(mo)-1]}/${y.slice(2)}`}
const clubsOf=(jogo:string)=>jogo.split(/\s+x\s+/i).map(s=>s.trim()).filter(Boolean)

export default function Relatorio({onChange}:{onChange:()=>Promise<unknown>|void}) {
 const [data,setData]=useState<Report|null>(null)
 const [error,setError]=useState('')
 const [month,setMonth]=useState('')
 const [club,setClub]=useState('')
 const [market,setMarket]=useState('')
 const [result,setResult]=useState('')
 const load=()=>api<Report>('/api/bet/relatorio').then(d=>{setData(d);setError('')}).catch((e:Error)=>setError(e.message))
 useEffect(()=>{load()},[])
 const reset=async()=>{
  if(!window.confirm('Apagar TODAS as apostas e reiniciar a banca? Esta ação não pode ser desfeita.'))return
  try{await api('/api/bet/apostas',{method:'DELETE'});await load();await onChange()}catch(e:any){setError(e.message)}
 }

 const months=useMemo(()=>!data?[]:[...new Set(data.apostas.map(b=>b.data_jogo.slice(0,7)))].sort().reverse(),[data])
 const clubs=useMemo(()=>{
  if(!data)return []
  const set=new Set<string>()
  data.apostas.forEach(b=>clubsOf(b.jogo).forEach(c=>set.add(c)))
  return [...set].sort((a,b)=>a.localeCompare(b,'pt'))
 },[data])
 const markets=useMemo(()=>!data?[]:[...new Set(data.apostas.map(b=>b.mercado_nome))].sort((a,b)=>a.localeCompare(b,'pt')),[data])

 const filtered=useMemo(()=>{
  if(!data)return []
  return data.apostas.filter(b=>{
   if(month&&!b.data_jogo.startsWith(month))return false
   if(club&&!clubsOf(b.jogo).some(c=>c===club))return false
   if(market&&b.mercado_nome!==market)return false
   if(result&&b.resultado!==result)return false
   return true
  })
 },[data,month,club,market,result])

 const filteredTotals=useMemo(()=>{
  const lucro=filtered.reduce((s,b)=>s+b.lucro,0)
  const stake=filtered.reduce((s,b)=>s+b.stake,0)
  const green=filtered.filter(b=>b.resultado==='green').length
  const red=filtered.filter(b=>b.resultado==='red').length
  return {apostas:filtered.length,lucro,green,red,stake_total:stake,
   roi_stake:stake?100*lucro/stake:null}
 },[filtered])

 if(error&&!data)return <p className="bf-alert err" role="alert">{error}</p>
 if(!data)return <p className="bf-muted pad">Carregando relatório...</p>
 const t=data.totais
 const filtering=!!(month||club||market||result)
 const show=filtering?filteredTotals:t
 return <section className="bf-main full">
  <h2 className="bf-h2">Relatório · Lucros e prejuízos</h2>
  {error&&<p className="bf-alert err" role="alert">{error}</p>}
  <div className="bf-stats">
   <Stat label="Banca inicial" value={brl(data.config.banca_inicial)}/>
   <Stat label="Banca atual" value={brl(data.config.banca_atual)} tone={plClass(data.config.banca_atual-data.config.banca_inicial)}/>
   <Stat label="Profit / Loss" value={brl(show.lucro)} tone={plClass(show.lucro)} hint={filtering?'No filtro atual':undefined}/>
   <Stat label="ROI sobre a stake" value={show.roi_stake==null?'—':`${num(show.roi_stake)}%`} tone={plClass(show.roi_stake)}/>
   <Stat label="Apostas" value={show.apostas}/>
   <Stat label="Green / Red" value={`${show.green} / ${show.red}`}/>
  </div>
  {t.apostas===0?<p className="bf-alert info">Nenhuma aposta feita ainda. Vá em Casa de Apostas e escolha uma odd.</p>:<>
   <h3 className="bf-h3">Profit / Loss mês a mês</h3>
   <div className="bf-tablewrap"><table className="bf-table months"><thead><tr><th></th>{data.meses.map(m=><th key={m.mes}>{monthLabel(m.mes)}</th>)}<th>Total</th></tr></thead><tbody>
    <tr><th>Profit / Loss</th>{data.meses.map(m=><td key={m.mes} className={plClass(m.lucro)}>{brl(m.lucro)}</td>)}<td className={plClass(t.lucro)}><strong>{brl(t.lucro)}</strong></td></tr>
    <tr><th>Apostas</th>{data.meses.map(m=><td key={m.mes}>{m.apostas}</td>)}<td>{t.apostas}</td></tr>
    <tr><th>Green / Red</th>{data.meses.map(m=><td key={m.mes}>{m.green} / {m.red}</td>)}<td>{t.green} / {t.red}</td></tr>
    <tr><th>Banca (fim do mês)</th>{data.meses.map(m=><td key={m.mes}><strong>{brl(m.banca)}</strong></td>)}<td><strong>{brl(data.config.banca_atual)}</strong></td></tr></tbody></table></div>
   <h3 className="bf-h3">Evolução da banca</h3>
   <LineChart points={data.curva.map(p=>({label:p.data?dateBr(p.data):'início',value:p.banca}))} baseline={data.config.banca_inicial}/>
   <h3 className="bf-h3">Apostas</h3>
   <div className="bf-form inline">
    <label>Mês<select value={month} onChange={e=>setMonth(e.target.value)}><option value="">Todos</option>{months.map(m=><option key={m} value={m}>{monthLabel(m)}</option>)}</select></label>
    <label>Clube<select value={club} onChange={e=>setClub(e.target.value)}><option value="">Todos</option>{clubs.map(c=><option key={c}>{c}</option>)}</select></label>
    <label>Mercado<select value={market} onChange={e=>setMarket(e.target.value)}><option value="">Todos</option>{markets.map(m=><option key={m}>{m}</option>)}</select></label>
    <label>Resultado<select value={result} onChange={e=>setResult(e.target.value)}><option value="">Todos</option><option value="green">Green</option><option value="red">Red</option></select></label>
    {filtering&&<button type="button" className="bf-btn small" onClick={()=>{setMonth('');setClub('');setMarket('');setResult('')}}>Limpar filtros</button>}
   </div>
   <p className="bf-muted">{filtering?`Mostrando ${filtered.length} de ${data.apostas.length} apostas.`:`${data.apostas.length} apostas.`}</p>
   <div className="bf-tablewrap tall"><table className="bf-table dense"><thead><tr><th>Jogo</th><th>Data</th><th>Mercado</th><th>Seleção</th><th>Tipo</th><th>Odd</th><th>Stake</th><th>Min.</th><th>Final</th><th>Resultado</th><th>P/L</th></tr></thead><tbody>
    {filtered.map(b=><tr key={b.id}><td>{b.jogo}<small className="bf-muted"> {b.campeonato}</small></td><td>{dateBr(b.data_jogo)}</td><td>{b.mercado_nome}</td><td>{b.selecao_nome}</td>
     <td><span className={`bf-chip ${b.lado}`}>{b.lado==='back'?'Back':'Lay'}</span></td><td>{odd(b.odd)}{b.odd_origem==='estimada'&&<span className="bf-tag warn" title="Odd estimada pelo modelo">est.</span>}</td>
     <td>{brl(b.stake)}</td><td>{b.minuto}'</td><td>{b.placar_final}</td><td className={b.resultado==='green'?'bf-pos':'bf-neg'}>{b.resultado==='green'?'Green':'Red'}</td><td className={plClass(b.lucro)}>{brl(b.lucro)}</td></tr>)}
    {!filtered.length&&<tr><td colSpan={11} className="bf-muted">Nenhuma aposta com esses filtros.</td></tr>}</tbody></table></div>
   <div className="bf-actions"><button type="button" className="bf-btn danger" onClick={reset}>Apagar apostas e reiniciar banca</button></div>
  </>}
 </section>
}
