import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import IdAutocomplete from './IdAutocomplete'

type Item={id:number;nome:string;[key:string]:unknown}
type ClubRow={club:string;country:string;country_type:string;club_country:string;games:number;wins:number;losses:number;win_rate:number|null;settled:number;profit:number|null;roi:number|null;all_games:number;recent_games:number}
type ClubMarket={market:string;label:string;kind:'back'|'lay';items:ClubRow[]}
type Ranking={markets:Record<string,ClubMarket>;eligible_count:number;use_odds:boolean;criterion:string;country_note:string}
type HistoryYear={year:number;games:number;wins:number;losses:number;win_rate:number|null;settled:number;profit:number|null;roi:number|null}
type History={club:string;country:string;club_country:string;country_type:string;market:string;market_label:string;years:HistoryYear[];total:{games:number;wins:number;losses:number;win_rate:number|null};use_odds:boolean}
const markets=[
 ['back_home','MO Casa'],['back_away','MO Fora'],['draw','Empate'],
 ['lay_home','Lay Casa'],['lay_away','Lay Fora'],
 ['lay_big_home','Lay Goleada Casa'],['lay_big_away','Lay Goleada Fora'],
 ['over05','Over 0,5'],['over15','Over 1,5'],['over25','Over 2,5'],
 ['under35','Under 3,5'],['btts','Ambas marcam — Sim'],
] as const
const fmt=(x:number|null|undefined)=>x==null?'—':x.toLocaleString('pt-BR',{maximumFractionDigits:1,minimumFractionDigits:1})
const count=(x:number)=>x.toLocaleString('pt-BR')
const cash=(x:number|null)=>x==null?'—':x.toLocaleString('pt-BR',{style:'currency',currency:'BRL'})

export default function ClubStatisticsPanel({useOdds,setUseOdds,continents,countries,allCompetitions,catalogLoading,sharedContinent=null,sharedCountry=null,sharedCompetition=null,hideFilters=false,applyToken=0}:{useOdds:boolean;setUseOdds:(fn:(previous:boolean)=>boolean)=>void;continents:Item[];countries:Item[];allCompetitions:Item[];catalogLoading:boolean;sharedContinent?:Item|null;sharedCountry?:Item|null;sharedCompetition?:Item|null;hideFilters?:boolean;applyToken?:number}){
 const [continent,setContinent]=useState<Item|null>(sharedContinent)
 const [country,setCountry]=useState<Item|null>(sharedCountry)
 const [competition,setCompetition]=useState<Item|null>(sharedCompetition)
 const [club,setClub]=useState('')
 const [candidates,setCandidates]=useState<string[]>([])
 const [suggestLoading,setSuggestLoading]=useState(false)
 const [market,setMarket]=useState<string>('back_home')
 const [rankings,setRankings]=useState<Ranking|null>(null)
 const [loading,setLoading]=useState(false)
 const [error,setError]=useState('')
 const [pending,setPending]=useState(false)
 const [showCount,setShowCount]=useState(40)
 const [picked,setPicked]=useState<ClubRow|null>(null)
 const [history,setHistory]=useState<History|null>(null)
 const [historyLoading,setHistoryLoading]=useState(false)
 const [historyError,setHistoryError]=useState('')
 const [applied,setApplied]=useState<{continent:string|null;country:string|null;competition:string|null;club:string|null;use_odds:boolean}|null>(null)
 const requestRef=useRef<AbortController|null>(null)
 const lastApplyToken=useRef(0)
 useEffect(()=>{
  if(!hideFilters)return
  setContinent(sharedContinent);setCountry(sharedCountry);setCompetition(sharedCompetition)
 },[hideFilters,sharedContinent?.id,sharedContinent?.nome,sharedCountry?.id,sharedCountry?.nome,sharedCompetition?.id,sharedCompetition?.nome])
 const filteredCountries=useMemo(()=>!continent?countries:countries.filter(c=>c.continente===continent.nome),[countries,continent?.nome])
 const filteredCompetitions=useMemo(()=>country?allCompetitions.filter(c=>Number(c.pais_id)===country.id):allCompetitions.filter(c=>!continent||c.continente===continent.nome),[country?.id,allCompetitions,continent?.nome])
 useEffect(()=>{
  // Não executa ranking ao mudar filtros ou mercado. Sugestões só quando o usuário digita.
  if(club.trim().length<2){setCandidates([]);setSuggestLoading(false);return}
  let active=true
  const controller=new AbortController()
  const handle=window.setTimeout(()=>{
   setSuggestLoading(true)
   const params=new URLSearchParams({q:club.trim(),limit:'120'})
   if(continent?.nome)params.set('continent',continent.nome)
   if(country?.nome)params.set('country',country.nome)
   if(competition?.nome)params.set('competition',competition.nome)
   api<{clubs:string[]}>(`/api/backtesting/club-candidates?${params.toString()}`,{signal:controller.signal})
    .then(result=>{if(active)setCandidates(result.clubs||[])})
    .catch(()=>{if(active)setCandidates([])})
    .finally(()=>{if(active)setSuggestLoading(false)})
  },300)
  return ()=>{active=false;window.clearTimeout(handle);controller.abort()}
 },[club,continent?.nome,country?.nome,competition?.nome])
 useEffect(()=>{setPicked(null);setHistory(null);setHistoryError('');setShowCount(40)},[market])
 useEffect(()=>{
  if(!picked||!applied)return
  let alive=true
  const controller=new AbortController()
  const timer=window.setTimeout(()=>controller.abort(),45000)
  setHistoryLoading(true);setHistory(null);setHistoryError('')
  api<History>('/api/backtesting/club-market-history',{method:'POST',signal:controller.signal,
    body:JSON.stringify({continent:applied.continent,country:picked.country,club:picked.club,market,
      competition:applied.competition,use_odds:applied.use_odds})})
    .then(data=>{if(alive)setHistory(data)})
    .catch((e:Error)=>{if(alive)setHistoryError(controller.signal.aborted?'A consulta excedeu 45 segundos.':e.message)})
    .finally(()=>{window.clearTimeout(timer);if(alive)setHistoryLoading(false)})
  return ()=>{alive=false;window.clearTimeout(timer);controller.abort()}
 },[picked?.club,picked?.country,market,applied])
 const apply=async()=>{
  if(loading)return
  requestRef.current?.abort()
  const controller=new AbortController();requestRef.current=controller
  setLoading(true);setError('');setPending(false);setPicked(null);setHistory(null)
  const activeContinent=hideFilters?sharedContinent:continent
  const activeCountry=hideFilters?sharedCountry:country
  const activeCompetition=hideFilters?sharedCompetition:competition
  const chosen={continent:activeContinent?.nome||null,country:activeCountry?.nome||null,competition:activeCompetition?.nome||null,club:club.trim()||null,use_odds:useOdds}
  const timer=window.setTimeout(()=>controller.abort(),45000)
  try{
   const data=await api<Ranking>('/api/backtesting/club-statistics',{method:'POST',signal:controller.signal,body:JSON.stringify(chosen)})
   setRankings(data);setApplied(chosen);setShowCount(40)
  }catch(e:any){setRankings(null);setApplied(null);setError(controller.signal.aborted?'A consulta excedeu 45 segundos. Tente selecionar um país ou campeonato.':e.message)}
  finally{window.clearTimeout(timer);if(requestRef.current===controller)requestRef.current=null;setLoading(false)}
 }
 useEffect(()=>{
  if(!hideFilters||!applyToken||applyToken===lastApplyToken.current)return
  lastApplyToken.current=applyToken
  void apply()
 // eslint-disable-next-line react-hooks/exhaustive-deps
 },[applyToken,hideFilters,sharedContinent?.nome,sharedCountry?.nome,sharedCompetition?.nome])
 const toggle=()=>{
  requestRef.current?.abort()
  setUseOdds(prev=>!prev);setPending(true);setRankings(null);setApplied(null)
  setPicked(null);setHistory(null);setError('')
 }
 const current=rankings?.markets?.[market]
 const rows=current?.items||[]
 const shown=rows.slice(0,showCount)
 const maxRate=Math.max(1,...shown.map(row=>row.win_rate||0))
 const chosenLabel=markets.find(([key])=>key===market)?.[1]||market
 return <>
  {!hideFilters&&<section className="bt-filter-panel bt-club-panel">
   <div className="bt-filter-head"><div><h2>Estatísticas por Clube</h2><p>País, campeonato e clube são opcionais. Apenas clubes com histórico suficiente entram nos gráficos.</p></div>
   </div>
   <div className="bt-filter-grid bt-club-filter-grid">
    <IdAutocomplete label="Continente" value={continent} options={continents} loading={catalogLoading} disabled={catalogLoading}
      onChange={v=>{setContinent(v);setCountry(null);setCompetition(null);setClub('')}} placeholder="Todos os continentes"/>
    <IdAutocomplete label="País" value={country} options={filteredCountries} loading={catalogLoading} disabled={catalogLoading}
      onChange={v=>{setCountry(v);setCompetition(null);setClub('')}} placeholder="Todos os países"/>
    <IdAutocomplete label="Campeonato" value={competition} options={filteredCompetitions} loading={catalogLoading} disabled={catalogLoading}
      onChange={v=>{setCompetition(v);if(v&&!country){const match=filteredCountries.find(x=>x.id===Number(v.pais_id));if(match)setCountry(match)}setClub('')}} placeholder="Todos os campeonatos"/>
    <div className="field"><label htmlFor="bt-club-search">Clube</label>
     <input id="bt-club-search" list="bt-club-suggestions" value={club} onChange={e=>setClub(e.target.value)} placeholder="Todos os clubes (pesquise por nome)" autoComplete="off"/>
     <datalist id="bt-club-suggestions">{candidates.map(name=><option key={name} value={name}/>)}</datalist>
     {suggestLoading&&<small className="bt-club-search-status">Procurando clubes elegíveis...</small>}
    </div>
   </div>
   <div className="bt-filter-actions"><button className="bt-primary" disabled={loading||catalogLoading} onClick={apply}>{loading?'Analisando...':'Aplicar filtros'}</button>
    <span>{pending?'Fonte alterada. Clique em Aplicar filtros para atualizar.':'Critério: mais de 500 jogos no histórico OU 100+ jogos nos últimos 3 anos.'}</span>
   </div>
  </section>}
  {hideFilters&&<div className="bt-filter-panel bt-club-panel" style={{marginBottom:12}}>
   <div className="bt-filter-grid bt-club-filter-grid">
    <div className="field"><label htmlFor="bt-club-search">Clube</label>
     <input id="bt-club-search" list="bt-club-suggestions" value={club} onChange={e=>setClub(e.target.value)} placeholder="Todos os clubes (pesquise por nome)" autoComplete="off"/>
     <datalist id="bt-club-suggestions">{candidates.map(name=><option key={name} value={name}/>)}</datalist>
     {suggestLoading&&<small className="bt-club-search-status">Procurando clubes elegíveis...</small>}
    </div>
   </div>
   <p className="bt-note" style={{padding:'0 18px 12px'}}>{pending?'Fonte alterada. Clique em Aplicar filtros acima para atualizar.':'Use Aplicar filtros acima. Critério: mais de 500 jogos no histórico OU 100+ jogos nos últimos 3 anos.'}</p>
  </div>}
  <nav className="bt-club-market-tabs" aria-label="Mercados das estatísticas por clube">{markets.map(([key,label])=><button key={key} type="button" className={market===key?'current':''} onClick={()=>setMarket(key)}>{label}</button>)}</nav>
  {error&&<p className="bt-error" role="alert">{error}</p>}
  {!rankings&&!loading&&!error&&<div className="bt-empty"><strong>Selecione o mercado e clique em Aplicar filtros</strong><p>Sem seleção, o sistema compara todos os clubes elegíveis. Nenhum filtro é obrigatório.</p></div>}
  {rankings&&<section className="bt-club-ranking">
   <div className="bt-league-overview-head"><h3>{chosenLabel} — comparação entre clubes</h3><span>{count(rows.length)} clubes com jogos neste mercado</span></div>
   <p className="bt-note">Clique no clube para abrir os últimos 10 anos. O país é obtido do cadastro de clubes, quando inequívoco; caso contrário, mostramos a região do campeonato identificada.</p>
   {!rows.length&&<p className="bt-note">Nenhum clube elegível possui partidas nesse mercado com os filtros aplicados.</p>}
   <div className="bt-club-ranking-rows">{shown.map(row=>{
    const open=picked?.club===row.club&&picked?.country===row.country
    return <Fragment key={`${row.country}-${row.club}`}>
     <button type="button" className={`bt-compare-row bt-compare-trigger ${open?'is-selected':''}`} aria-expanded={open}
      onClick={()=>setPicked(open?null:row)} aria-label={`Histórico de ${row.club}, ${row.country}, mercado ${chosenLabel}`}>
      <span className="bt-compare-labels"><strong>{row.club}</strong><small>{row.club_country} · {count(row.games)} jogos · {count(row.all_games)} histórico / {count(row.recent_games)} em 3 anos</small></span>
      <span className="bt-compare-bar"><span style={{width:`${Math.max(2,(row.win_rate||0)/maxRate*100)}%`}}/></span>
      <span className="bt-compare-value">{row.win_rate==null?'—':`${fmt(row.win_rate)}%`}</span>
     </button>
     {open&&<div className="bt-compare-detail" role="region" aria-label={`Histórico dos últimos 10 anos de ${row.club}`}>
       <div className="bt-compare-detail-head"><div><strong>{row.club} · {chosenLabel}</strong><small>{row.country_type}: {row.club_country} · últimos 10 anos-calendário (ano atual parcial)</small></div><button type="button" className="bt-quiet" onClick={()=>setPicked(null)}>Fechar</button></div>
       {historyLoading&&<p className="bt-note">Carregando os últimos 10 anos...</p>}
       {historyError&&<p className="bt-error" role="alert">{historyError}</p>}
       {history&&!historyLoading&&<><div className="bt-compare-year-bars">
        {history.years.map(y=><div className="bt-compare-year" key={y.year} title={`${y.year}: ${count(y.wins)} acertos, ${count(y.losses)} erros, ${count(y.games)} jogos`}>
         <strong>{y.year}</strong><div className="bt-compare-year-track"><span style={{width:`${y.win_rate||0}%`}}/></div>
         <strong>{y.win_rate==null?'—':`${fmt(y.win_rate)}%`}</strong>
         <small>{count(y.games)} jogos · {count(y.wins)}G/{count(y.losses)}R</small>
         {history.use_odds&&<small>{y.roi==null?'ROI —':`ROI ${fmt(y.roi)}%`}</small>}
        </div>)}
       </div><p className="bt-compare-total">Total: {count(history.total.games)} jogos · {count(history.total.wins)} acertos · {count(history.total.losses)} erros · Win Rate {history.total.win_rate==null?'—':`${fmt(history.total.win_rate)}%`}</p></>}
       {applied?.use_odds&&<p className="bt-note">Mercados sem odds reais apresentam somente frequência de acerto; não há lucro ou ROI simulado.</p>}
     </div>}
    </Fragment>
   })}</div>
   {rows.length>shown.length&&<button className="bt-secondary" onClick={()=>setShowCount(value=>value+40)}>Mostrar mais clubes ({count(rows.length-shown.length)} restantes)</button>}
   <p className="bt-note">{rankings.criterion} Os gráficos usam {rankings.use_odds?'jogos conciliados com historico_odds':'partidas de historico_jogos'}. No modo Com odds, ROI e lucro só são calculados com cotações reais do próprio mercado.</p>
  </section>}
 </>
}
