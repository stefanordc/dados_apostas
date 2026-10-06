import { useEffect, useMemo, useState } from 'react'
import { api, query } from '../api'
import IdAutocomplete from '../components/IdAutocomplete'

type Item = { id:number; nome:string; pais_id?:number; pais?:string; principal?:boolean }
type Metric = 'elo'|'offense'|'defense'|'market'|'5'|'10'|'20'|'season'|'history'|'over15'|'over25'|'btts'
type RankingResponse = { rows:any[]; direction:string; unit:string; warning?:string; defense_lower_is_better?:boolean }
type FiltersResponse = { countries:Item[]; competitions:Item[]; seasons:string[]; current_season?:string|null }
type SortDirection = 'asc'|'desc'
type SortKey = 'rank'|'club'|'country'|'metric'|'rate'|'mgm'|'mgs'|'games'|'wins'|'draws'|'losses'|'gf'|'ga'|'gd'

const TABS:{key:Metric;label:string}[] = [
  {key:'elo',label:'ELO'},
  {key:'offense',label:'Força ofensiva'},
  {key:'defense',label:'Força defensiva'},
  {key:'market',label:'Valor de mercado'},
  {key:'over15',label:'Over 1,5'},
  {key:'over25',label:'Over 2,5'},
  {key:'btts',label:'Ambos marcam'},
  {key:'5',label:'Desempenho (5 jogos)'},
  {key:'10',label:'Desempenho (10 jogos)'},
  {key:'20',label:'Desempenho (20 jogos)'},
  {key:'season',label:'Desempenho (Temporada)'},
  {key:'history',label:'Desempenho (Histórico)'},
]

const fmt=(v:any,d=1)=>v===null||v===undefined||!Number.isFinite(Number(v))?'—':Number(v).toLocaleString('pt-BR',{minimumFractionDigits:d,maximumFractionDigits:d})
const fmtInt=(v:any)=>v===null||v===undefined||!Number.isFinite(Number(v))?'—':Math.trunc(Number(v)).toLocaleString('pt-BR')
const fmtSignedInt=(v:any)=>{
  if(v===null||v===undefined||!Number.isFinite(Number(v)))return '—'
  const n=Math.trunc(Number(v))
  return `${n>0?'+':''}${n.toLocaleString('pt-BR')}`
}

function money(value:any,currency='EUR'){
  if(value===null||value===undefined||!Number.isFinite(Number(value)))return '—'
  return new Intl.NumberFormat('pt-BR',{style:'currency',currency,maximumFractionDigits:0}).format(Number(value))
}

function numeric(v:any){
  const n=Number(v)
  return Number.isFinite(n)?n:null
}

export default function Rankings(){
 const[countries,setCountries]=useState<Item[]>([])
 const[competitions,setCompetitions]=useState<Item[]>([])
 const[seasons,setSeasons]=useState<string[]>([])
 const[currentSeason,setCurrentSeason]=useState('')
 const[country,setCountry]=useState<Item|null>(null)
 const[competition,setCompetition]=useState<Item|null>(null)
 const[season,setSeason]=useState('')
 const[venue,setVenue]=useState('all')
 const[tab,setTab]=useState<Metric>('elo')
 const[data,setData]=useState<RankingResponse>({rows:[],direction:'desc',unit:''})
 const[loading,setLoading]=useState(false)
 const[sortKey,setSortKey]=useState<SortKey|null>(null)
 const[sortDirection,setSortDirection]=useState<SortDirection>('desc')

 useEffect(()=>{
   api<FiltersResponse>('/api/rankings/filters').then(d=>{
     setCountries(d.countries)
     setCompetitions(d.competitions)
     setSeasons(d.seasons||[])
     const current=d.current_season||d.seasons?.[0]||''
     setCurrentSeason(current)
     setSeason(current)
   })
 },[])

 useEffect(()=>{
   setCompetition(null)
   api<FiltersResponse>(`/api/rankings/filters?${query({country_id:country?.id})}`).then(d=>{
     setCompetitions(d.competitions)
     setSeasons(d.seasons||[])
     if(season && season!=='all' && d.seasons?.length && !d.seasons.includes(season)){
       setSeason(d.current_season||d.seasons[0]||'')
     }
   })
 },[country?.id])

 useEffect(()=>{
   if(!season)return
   let active=true
   setLoading(true)
   api<RankingResponse>(`/api/rankings?${query({metric:tab,country_id:country?.id,competition_id:competition?.id,season,venue})}`)
    .then(d=>{if(active)setData(d)})
    .finally(()=>{if(active)setLoading(false)})
   return()=>{active=false}
 },[tab,country?.id,competition?.id,season,venue])

 // Ao trocar de ranking, volta para a ordenação nativa daquele ranking.
 useEffect(()=>{
   setSortKey(null)
   setSortDirection('desc')
 },[tab])

 const isPerformance=useMemo(()=>['5','10','20','season','history'].includes(tab),[tab])
 const isGoalRanking=useMemo(()=>['over15','over25','btts'].includes(tab),[tab])
 const isOverRanking=useMemo(()=>['over15','over25'].includes(tab),[tab])
 const hasRateColumn=isGoalRanking
 const showDetailedStats=isPerformance||isGoalRanking
 const metricLabel=TABS.find(x=>x.key===tab)?.label||''
 const displayMetricLabel=season==='all'&&tab==='elo'?'ELO médio':season==='all'&&tab==='market'?'Valor de mercado acumulado':metricLabel

 function mainValue(r:any){
   if(tab==='market')return money(r.valor,r.moeda)
   if(tab==='elo')return fmt(r.valor,1)
   if(tab==='offense'||tab==='defense')return fmt(r.valor,2)
   if(isGoalRanking)return `${fmtInt(r.valor)} jogos`
   return `${fmt(r.valor,1)}%`
 }

 function valueForSort(r:any,key:SortKey){
   switch(key){
     case 'rank': return numeric(r.posicao)
     case 'club': return String(r.clube||'')
     case 'country': return String(r.pais||'')
     case 'metric': return numeric(r.valor)
     case 'rate': return numeric(r.taxa)
     case 'mgm': return numeric(r.mgm)
     case 'mgs': return numeric(r.mgs)
     case 'games': return numeric(r.jogos)
     case 'wins': return numeric(r.vitorias)
     case 'draws': return numeric(r.empates)
     case 'losses': return numeric(r.derrotas)
     case 'gf': return numeric(r.gols_marcados)
     case 'ga': return numeric(r.gols_sofridos)
     case 'gd': return numeric(r.saldo_gols)
   }
 }

 function requestSort(key:SortKey){
   if(sortKey===key){
     setSortDirection(d=>d==='desc'?'asc':'desc')
     return
   }
   setSortKey(key)
   setSortDirection(key==='club'||key==='country'?'asc':'desc')
 }

 const sortedRows=useMemo(()=>{
   if(!sortKey)return data.rows
   const dir=sortDirection==='asc'?1:-1
   return [...data.rows].sort((a:any,b:any)=>{
     const av=valueForSort(a,sortKey)
     const bv=valueForSort(b,sortKey)
     if(av===null||av===undefined)return 1
     if(bv===null||bv===undefined)return -1
     if(typeof av==='string'||typeof bv==='string'){
       return String(av).localeCompare(String(bv),'pt-BR',{sensitivity:'base',numeric:true})*dir
     }
     if(av===bv)return String(a.clube||'').localeCompare(String(b.clube||''),'pt-BR',{sensitivity:'base'})
     return (Number(av)-Number(bv))*dir
   })
 },[data.rows,sortKey,sortDirection])

 function SortHeader({sort,label,className}:{sort:SortKey;label:string;className?:string}){
   const active=sortKey===sort
   return <th className={`sortable-ranking-th ${active?'active-sort':''} ${className||''}`}>
    <button type="button" onClick={()=>requestSort(sort)} title={`Ordenar por ${label}`}>
      <span>{label}</span>
      <span className="ranking-sort-icon" aria-hidden="true">{active?(sortDirection==='desc'?'▼':'▲'):'↕'}</span>
    </button>
   </th>
 }

 return <section className="page rankings-page">
  <div className="page-header"><div><span className="eyebrow">LEAGUE INTELLIGENCE</span><h1>Rankings</h1><p>Compare os clubes por rating, força, mercado, gols e desempenho.</p></div></div>

  <div className="panel rankings-filter-bar">
   <IdAutocomplete label="País" value={country} options={countries} onChange={setCountry}/>
   <IdAutocomplete label="Campeonato" value={competition} options={competitions} onChange={setCompetition}/>
   <div className="field"><label>Temporada</label><select value={season} onChange={e=>setSeason(e.target.value)}><option value="all">Todas as temporadas</option>{seasons.map(s=><option key={s} value={s}>{s}</option>)}</select></div>
   <div className="field"><label>Mando de campo</label><select value={venue} onChange={e=>setVenue(e.target.value)}><option value="all">Todos</option><option value="home">Mandante</option><option value="away">Visitante</option></select></div>
   <button className="secondary rankings-clear" onClick={()=>{setCountry(null);setCompetition(null);setSeason(currentSeason);setVenue('all')}}>Limpar filtros</button>
  </div>

  <div className="rankings-tabs">{TABS.map(t=><button key={t.key} className={tab===t.key?'active':''} onClick={()=>setTab(t.key)}>{t.label}</button>)}</div>

  {data.warning&&<div className="notice info">{data.warning}</div>}
  {(tab==='elo'||tab==='market')&&venue!=='all'&&<div className="notice info">O mando é aplicado às médias de gols exibidas, mas não altera {tab==='elo'?'o ELO':'o valor de mercado'}.</div>}
  {season==='all'&&<div className="notice info">Todas as temporadas: o histórico é consolidado em um único ranking. No ELO, o valor principal é a média dos ELOs finais por temporada.</div>}

  <div className="panel rankings-panel">
   <div className="panel-title"><div><h2>{displayMetricLabel}</h2><span>{data.rows.length.toLocaleString('pt-BR')} clubes no recorte · {season==='all'?'Todas as temporadas':season}</span></div>{tab==='defense'&&<span>Menor índice = melhor defesa</span>}</div>
   {loading?<div className="empty-state">Calculando ranking...</div>:<div className="table-scroll"><table className="rankings-table"><thead><tr>
    <SortHeader sort="rank" label="#"/>
    <SortHeader sort="club" label="Clube"/>
    <SortHeader sort="country" label="País"/>
    <SortHeader sort="metric" label={displayMetricLabel}/>
    {hasRateColumn&&<SortHeader sort="rate" label="% dos jogos"/>}
    <SortHeader sort="mgm" label="MGM"/>
    <SortHeader sort="mgs" label="MGS"/>
    {showDetailedStats&&<>
      <SortHeader sort="games" label="J"/>
      <SortHeader sort="wins" label="V"/>
      <SortHeader sort="draws" label="E"/>
      <SortHeader sort="losses" label="D"/>
      <SortHeader sort="gf" label="GM"/>
      <SortHeader sort="ga" label="GS"/>
      <SortHeader sort="gd" label="SG"/>
    </>}
   </tr></thead><tbody>{sortedRows.map((r:any,index:number)=><tr key={`${r.clube_id}-${r.campeonato_id||''}-${r.moeda||''}`}>
    <td><span className={`rank-position ${index<3?'top':''}`}>{sortKey?index+1:r.posicao}</span></td>
    <td><div className="club-inline">{r.escudo_url?<img src={r.escudo_url}/>:<span className="mini-crest">{String(r.clube||'?')[0]}</span>}<strong>{r.clube}</strong></div></td>
    <td>{r.pais||'—'}</td>
    <td><strong className="ranking-main-value">{mainValue(r)}</strong>{tab==='market'&&<small className="ranking-currency">{r.moeda}</small>}</td>
    {hasRateColumn&&<td><strong>{fmt(r.taxa,1)}%</strong></td>}
    <td>{fmt(r.mgm,2)}</td>
    <td>{fmt(r.mgs,2)}</td>
    {showDetailedStats&&<><td>{fmtInt(r.jogos)}</td><td>{fmtInt(r.vitorias)}</td><td>{fmtInt(r.empates)}</td><td>{fmtInt(r.derrotas)}</td><td>{fmtInt(r.gols_marcados)}</td><td>{fmtInt(r.gols_sofridos)}</td><td>{fmtSignedInt(r.saldo_gols)}</td></>}
   </tr>)}</tbody></table></div>}
   {!loading&&!data.rows.length&&<div className="empty-state">Nenhum clube com dados suficientes para este recorte.</div>}
  </div>
 </section>
}
