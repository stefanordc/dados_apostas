import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'

type MarketItem = {key:string;label:string}
type Group = {key:string;label:string;markets:MarketItem[]}
type FilterCombination = {continent:string;country:string;competition:string;division:string;format:string}
type FilterOptions = {combinations:FilterCombination[];continents:string[];countries:string[];competitions:string[];divisions:string[];formats:string[];source:string}
type Measure = {games:number;green:number;red:number;win_rate:number|null;profit:number;roi:number|null;good_run:number;bad_run:number}
type Range = {low:number;high:number;training:Measure;validation:Measure;total:Measure}
type Report = {group:string;group_label:string;markets:{key:string;label:string;metrics:Measure;fair_odd:number|null;best_ranges:Range[];start:string|null;end:string|null}[];scanned:number;duplicates:number;truncated:boolean;sample_note:string;source:string}
const number = (n:number|null|undefined,digits=1)=>n==null?'—':n.toLocaleString('pt-BR',{minimumFractionDigits:digits,maximumFractionDigits:digits})
const money = (n:number)=>n.toLocaleString('pt-BR',{style:'currency',currency:'BRL'})

export default function Scanner(){
 const [groups,setGroups]=useState<Group[]>([])
 const [group,setGroup]=useState('mo_ft')
 const [continent,setContinent]=useState('')
 const [country,setCountry]=useState('')
 const [competition,setCompetition]=useState('')
 const [division,setDivision]=useState('')
 const [format,setFormat]=useState('')
 const [options,setOptions]=useState<FilterOptions|null>(null)
 const [optionsLoading,setOptionsLoading]=useState(true)
 const [optionsError,setOptionsError]=useState('')
 const [from,setFrom]=useState('')
 const [to,setTo]=useState('')
 const [error,setError]=useState('')
 const [loading,setLoading]=useState(false)
 const [report,setReport]=useState<Report|null>(null)
 const [selected,setSelected]=useState('')
 useEffect(()=>{api<{groups:Group[]}>('/api/analysis-v3/scanner/catalog').then(r=>{setGroups(r.groups||[]);if(r.groups?.length)setGroup(r.groups[0].key)}).catch((e:Error)=>setError(e.message))},[])
 useEffect(()=>{
  let active=true
  api<FilterOptions>('/api/analysis-v3/scanner/filter-options')
   .then(r=>{if(active)setOptions(r)})
   .catch((e:Error)=>{if(active)setOptionsError(`Não foi possível carregar os filtros: ${e.message}`)})
   .finally(()=>{if(active)setOptionsLoading(false)})
  return ()=>{active=false}
 },[])
 const unique=(items:string[])=>[...new Set(items.filter(Boolean))].sort((a,b)=>a.localeCompare(b,'pt-BR'))
 const continentRows=useMemo(()=>options?.combinations.filter(r=>!continent||r.continent===continent)||[],[options,continent])
 const countries=useMemo(()=>unique(continentRows.map(r=>r.country)),[continentRows])
 const countryRows=useMemo(()=>continentRows.filter(r=>!country||r.country===country),[continentRows,country])
 const competitions=useMemo(()=>unique(countryRows.map(r=>r.competition)),[countryRows])
 const competitionRows=useMemo(()=>countryRows.filter(r=>!competition||r.competition===competition),[countryRows,competition])
 const divisions=useMemo(()=>unique(competitionRows.map(r=>r.division)),[competitionRows])
 const divisionRows=useMemo(()=>competitionRows.filter(r=>!division||r.division===division),[competitionRows,division])
 const formats=useMemo(()=>unique(divisionRows.map(r=>r.format)),[divisionRows])
 const current=useMemo(()=>groups.find(g=>g.key===group),[groups,group])
 const analyzed=report?.markets.find(m=>m.key===selected)||report?.markets[0]
 const apply=async()=>{
  if(loading)return
  const year_from=from?Number(from):null;const year_to=to?Number(to):null
  if((year_from&&(!Number.isInteger(year_from)||year_from<1850||year_from>2100))||(year_to&&(!Number.isInteger(year_to)||year_to<1850||year_to>2100))||(year_from&&year_to&&year_from>year_to)){
   setError('Informe um intervalo de anos válido.');return
  }
  setError('');setLoading(true);setReport(null)
  try{
   const r=await api<Report>('/api/analysis-v3/scanner/analyze',{method:'POST',body:JSON.stringify({group,continent:continent||null,country:country||null,competition:competition||null,
    division:division||null,format:format||null,year_from,year_to})})
   setReport(r);setSelected(r.markets[0]?.key||'')
  }catch(e:any){setError(e.message)}finally{setLoading(false)}
 }
 return <div className="a3-page">
  <header className="a3-head"><div><small>FOOTBALL INTELLIGENCE · ODDS</small><h1>Scanner</h1><p>Histórico real da tabela <code>odds</code>. Odd de equilíbrio, faixas de preço, ROI e sequências de acertos e erros.</p></div><span className="a3-source">Fonte: public.odds</span></header>
  <section className="a3-panel">
   <h2>Selecione o grupo de mercados</h2>
   <nav className="a3-tabs" aria-label="Grupos de mercado">{groups.map(g=><button type="button" key={g.key} className={g.key===group?'active':''} onClick={()=>{setGroup(g.key);setReport(null);setSelected('')}}>{g.label}</button>)}</nav>
   <div className="a3-filters a3-scanner-filters">
    <label>Continente<select aria-label="Continente" value={continent} disabled={optionsLoading||!!optionsError} onChange={e=>{setContinent(e.target.value);setCountry('');setCompetition('');setDivision('');setFormat('');setReport(null)}}>
      <option value="">Todos os continentes</option>{options?.continents.map(c=><option key={c} value={c}>{c}</option>)}
     </select></label>
    <label>País<select aria-label="País" value={country} disabled={optionsLoading||!!optionsError} onChange={e=>{setCountry(e.target.value);setCompetition('');setDivision('');setFormat('');setReport(null)}}>
      <option value="">Todos os países</option>{countries.map(c=><option key={c} value={c}>{c}</option>)}
     </select></label>
    <label>Campeonato<select aria-label="Campeonato" value={competition} disabled={optionsLoading||!!optionsError} onChange={e=>{setCompetition(e.target.value);setDivision('');setFormat('');setReport(null)}}>
      <option value="">Todos os campeonatos</option>{competitions.map(c=><option key={c} value={c}>{c}</option>)}
     </select></label>
    <label>Divisão<select aria-label="Divisão" value={division} disabled={optionsLoading||!!optionsError} onChange={e=>{setDivision(e.target.value);setFormat('');setReport(null)}}>
      <option value="">Todas as divisões</option>{divisions.map(d=><option key={d} value={d}>{d}</option>)}
     </select></label>
    <label>Formato<select aria-label="Formato" value={format} disabled={optionsLoading||!!optionsError} onChange={e=>{setFormat(e.target.value);setReport(null)}}>
      <option value="">Todos os formatos</option>{formats.map(f=><option key={f} value={f}>{f}</option>)}
     </select></label>
    <label>Ano — de<input value={from} type="number" onChange={e=>{setFrom(e.target.value);setReport(null)}} placeholder="Início"/></label>
    <label>Ano — até<input value={to} type="number" onChange={e=>{setTo(e.target.value);setReport(null)}} placeholder="Hoje"/></label>
   </div>
   {optionsLoading&&<p className="a3-note" role="status">Carregando opções da tabela odds...</p>}
   {optionsError&&<p className="a3-error" role="alert">{optionsError} Recarregue a página para tentar novamente.</p>}
   {options&&!options.combinations.length&&<p className="a3-note">Não há países ou campeonatos disponíveis em public.odds.</p>}
   <div className="a3-actions"><button type="button" onClick={apply} disabled={loading||!current}>{loading?'Calculando...':'Analisar mercados'}</button><span>Filtros opcionais e encadeados. O cálculo só acontece ao clicar em Analisar mercados.</span></div>
  </section>
  {error&&<p className="a3-error" role="alert">{error}</p>}
  {report&&<>
   <p className="a3-note">{number(report.scanned,0)} registros examinados · {number(report.duplicates,0)} duplicidades ignoradas. {report.truncated?'Foram analisados os 80.000 jogos mais recentes; restrinja o período para resultados completos.':''}</p>
   <nav className="a3-tabs" aria-label="Mercados analisados">{report.markets.map(m=><button key={m.key} className={analyzed?.key===m.key?'active':''} onClick={()=>setSelected(m.key)}>{m.label}</button>)}</nav>
   {analyzed&&<>
    <div className="a3-cards">
     <article><small>Jogos com odd real</small><strong>{number(analyzed.metrics.games,0)}</strong><span>{analyzed.start||'—'} a {analyzed.end||'—'}</span></article>
     <article><small>Win Rate</small><strong>{number(analyzed.metrics.win_rate)}%</strong><span>{number(analyzed.metrics.green,0)} Green / {number(analyzed.metrics.red,0)} Red</span></article>
     <article><small>Odd mínima de equilíbrio</small><strong>{number(analyzed.fair_odd,2)}</strong><span>1 ÷ frequência de acertos</span></article>
     <article><small>ROI histórico</small><strong className={(analyzed.metrics.roi||0)>0?'a3-good':'a3-bad'}>{number(analyzed.metrics.roi)}%</strong><span>{money(analyzed.metrics.profit)} · R$ 100 por aposta</span></article>
     <article><small>Maior good run</small><strong className="a3-good">{analyzed.metrics.good_run}</strong><span>Acertos consecutivos</span></article>
     <article><small>Maior bad run</small><strong className="a3-bad">{analyzed.metrics.bad_run}</strong><span>Erros consecutivos</span></article>
    </div>
    <section className="a3-panel"><h2>Faixas de odds com resultados historicamente favoráveis</h2>
     <p className="a3-note">{report.sample_note}</p>
     {analyzed.best_ranges.length ? <div className="a3-table-wrap"><table className="a3-table"><thead><tr><th>Faixa</th><th>Jogos</th><th>WR</th><th>ROI 70% inicial</th><th>ROI 30% posterior</th><th>ROI total</th><th>Maior Green</th><th>Maior Red</th></tr></thead><tbody>
      {analyzed.best_ranges.map(r=><tr key={`${r.low}-${r.high}`}><td><strong>{number(r.low,2)} – {number(r.high,2)}</strong></td><td>{number(r.total.games,0)}</td><td>{number(r.total.win_rate)}%</td><td>{number(r.training.roi)}%</td><td>{number(r.validation.roi)}%</td><td>{number(r.total.roi)}%</td><td>{r.total.good_run}</td><td>{r.total.bad_run}</td></tr>)}
     </tbody></table></div>:<p>Não existe faixa com amostra suficiente e ROI positivo nas duas janelas. Nenhuma faixa será apresentada como lucrativa.</p>}
    </section>
   </>}
  </>}
 </div>
}
