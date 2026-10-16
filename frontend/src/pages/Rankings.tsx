import { useEffect, useMemo, useState } from 'react'
import { api, query } from '../api'
import IdAutocomplete from '../components/IdAutocomplete'

type Item = { id:number; nome:string; pais_id?:number; pais?:string; principal?:boolean }
type Metric =
  | 'elo'|'offense'|'defense'|'market'|'5'|'10'|'20'|'season'|'history'|'over15'|'over25'|'btts'
  | 'opens_score'|'opens_and_wins'|'opens_and_equalized'|'opens_and_overturned'
  | 'goals_band_0_15'|'goals_band_16_30'|'goals_band_31_45'|'goals_band_46_60'
  | 'goals_band_61_75'|'goals_band_76_90'|'goals_band_90p'
  | 'shots'|'shots_on_target'|'shots_per_game'|'shots_per_goal'|'sot_per_goal'
  | 'pass_accuracy'|'possession'|'tackles'|'xg'|'big_chances'|'big_chances_scored'
  | 'corners'|'interceptions'|'recoveries'|'duel_pct'|'dribble_pct'|'tackle_pct'
  | 'shots_in_box'|'saves'|'yellow_cards'|'red_cards'|'fouls'|'offsides'|'woodwork'
  | 'crosses'|'long_balls'|'through_balls'
type ColumnDef = { key:string; label:string; decimals?:number|null; format?:string; suffix?:string; role?:string }
type RankingResponse = {
  rows:any[]; direction:string; unit:string; warning?:string; defense_lower_is_better?:boolean
  decimals?:number; lower_is_better?:boolean; columns?:ColumnDef[]
}
type FiltersResponse = { countries:Item[]; competitions:Item[]; seasons:string[]; years?:number[]; current_season?:string|null; divisions?:string[]; formats?:string[]; division_formats?:{divisao:string;formato:string}[] }
type SortDirection = 'asc'|'desc'

const TAB_GROUPS:{id:string;title:string;tabs:{key:Metric;label:string}[]}[] = [
  {id:'classicos', title:'Clássicos', tabs:[
    {key:'elo',label:'ELO'},
    {key:'offense',label:'Força ofensiva'},
    {key:'defense',label:'Força defensiva'},
    {key:'market',label:'Valor de mercado'},
  ]},
  {id:'gols_mercados', title:'Gols e mercados', tabs:[
    {key:'over15',label:'Over 1,5'},
    {key:'over25',label:'Over 2,5'},
    {key:'btts',label:'Ambos marcam'},
  ]},
  {id:'gols_resultado', title:'Gols e Resultado', tabs:[
    {key:'opens_score',label:'Abre o placar'},
    {key:'opens_and_wins',label:'Abre o placar e vence'},
    {key:'opens_and_equalized',label:'Abre o placar e sofre o empate'},
    {key:'opens_and_overturned',label:'Abre o placar e sofre a virada'},
    {key:'goals_band_0_15',label:'Gols por minuto (0 - 15)'},
    {key:'goals_band_16_30',label:'Gols por minuto (16 - 30)'},
    {key:'goals_band_31_45',label:'Gols por minuto (31 - 45)'},
    {key:'goals_band_46_60',label:'Gols por minuto (46 - 60)'},
    {key:'goals_band_61_75',label:'Gols por minuto (61 - 75)'},
    {key:'goals_band_76_90',label:'Gols por minuto (76 - 90)'},
    {key:'goals_band_90p',label:'Gols por minuto (90+)'},
  ]},
  {id:'desempenho', title:'Desempenho', tabs:[
    {key:'5',label:'Desempenho (5 jogos)'},
    {key:'10',label:'Desempenho (10 jogos)'},
    {key:'20',label:'Desempenho (20 jogos)'},
    {key:'season',label:'Desempenho (Temporada)'},
    {key:'history',label:'Desempenho (Histórico)'},
  ]},
  {id:'finalizacoes', title:'Finalizações e criação', tabs:[
    {key:'shots',label:'Finalizações'},
    {key:'shots_on_target',label:'Finalizações certas'},
    {key:'shots_per_game',label:'Finalizações por jogo'},
    {key:'shots_per_goal',label:'Finalizações para fazer 1 gol'},
    {key:'sot_per_goal',label:'Finalizações certas para fazer 1 gol'},
    {key:'shots_in_box',label:'Chutes na área'},
    {key:'xg',label:'xG médio'},
    {key:'big_chances',label:'Grandes chances'},
    {key:'big_chances_scored',label:'Grandes chances convertidas'},
  ]},
  {id:'posse', title:'Posse e passe', tabs:[
    {key:'possession',label:'Posse de bola média'},
    {key:'pass_accuracy',label:'% Passes certos'},
    {key:'crosses',label:'Cruzamentos certos'},
    {key:'long_balls',label:'Bolas longas certas'},
    {key:'through_balls',label:'Passes em profundidade'},
  ]},
  {id:'defesa', title:'Defesa e duelos', tabs:[
    {key:'tackles',label:'Desarmes'},
    {key:'tackle_pct',label:'% Desarmes certos'},
    {key:'interceptions',label:'Interceptações'},
    {key:'recoveries',label:'Recuperações'},
    {key:'duel_pct',label:'% Duelos vencidos'},
    {key:'dribble_pct',label:'% Dribles certos'},
    {key:'saves',label:'Defesas do goleiro'},
  ]},
  {id:'disciplina', title:'Disciplina e outros', tabs:[
    {key:'corners',label:'Escanteios'},
    {key:'fouls',label:'Faltas'},
    {key:'offsides',label:'Impedimentos'},
    {key:'yellow_cards',label:'Cartões amarelos'},
    {key:'red_cards',label:'Cartões vermelhos'},
    {key:'woodwork',label:'Bolas na trave'},
  ]},
]
const TABS = TAB_GROUPS.flatMap(g=>g.tabs)
const SOFASCORE_KEYS = new Set([
  'shots','shots_on_target','shots_per_game','shots_per_goal','sot_per_goal','pass_accuracy','possession','tackles',
  'xg','big_chances','big_chances_scored','corners','interceptions','recoveries','duel_pct','dribble_pct','tackle_pct',
  'shots_in_box','saves','yellow_cards','red_cards','fouls','offsides','woodwork','crosses','long_balls','through_balls',
])
const GOALS_RESULT_KEYS = new Set(TAB_GROUPS.find(g=>g.id==='gols_resultado')!.tabs.map(t=>t.key))
const MIN_GAMES_OPTIONS = [1, 3, 5, 10, 15, 20, 30, 50]

function yearsFromSeasons(seasons:string[]){
  const out=new Set<number>()
  for(const season of seasons){
    for(const part of String(season||'').split(/[/\-]/)){
      const n=Number(part)
      if(Number.isInteger(n)&&n>=1850&&n<=2100)out.add(n)
    }
  }
  return [...out].sort((a,b)=>b-a)
}

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
 const[years,setYears]=useState<number[]>([])
 const[divisions,setDivisions]=useState<string[]>([])
 const[formats,setFormats]=useState<string[]>([])
 const[divisionFormats,setDivisionFormats]=useState<{divisao:string;formato:string}[]>([])
 const[currentSeason,setCurrentSeason]=useState('')
 const[country,setCountry]=useState<Item|null>(null)
 const[competition,setCompetition]=useState<Item|null>(null)
 const[season,setSeason]=useState('')
 const[year,setYear]=useState('all')
 const[minGames,setMinGames]=useState('5')
 const[divisao,setDivisao]=useState('')
 const[formato,setFormato]=useState('')
 const[venue,setVenue]=useState('all')
 const[subject,setSubject]=useState(TAB_GROUPS[0].id)
 const[tab,setTab]=useState<Metric>('elo')
 const[data,setData]=useState<RankingResponse>({rows:[],direction:'desc',unit:''})
 const[loading,setLoading]=useState(false)
 const[sortKey,setSortKey]=useState<string|null>(null)
 const[sortDirection,setSortDirection]=useState<SortDirection>('desc')

 const activeGroup=TAB_GROUPS.find(g=>g.id===subject)||TAB_GROUPS[0]
 const yearOptions=useMemo(()=>years.length?years:yearsFromSeasons(seasons),[years,seasons])
 const formatsForDivision=useMemo(()=>{
  if(!divisao)return formats
  return [...new Set(divisionFormats.filter(p=>p.divisao===divisao).map(p=>p.formato).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'pt-BR'))
 },[divisao,formats,divisionFormats])

 useEffect(()=>{
   api<FiltersResponse>('/api/rankings/filters').then(d=>{
     setCountries(d.countries)
     setCompetitions(d.competitions)
     const nextSeasons=d.seasons||[]
     setSeasons(nextSeasons)
     setYears((d.years&&d.years.length)?d.years:yearsFromSeasons(nextSeasons))
     setDivisions(d.divisions||[])
     setFormats(d.formats||[])
     setDivisionFormats(d.division_formats||[])
     const current=d.current_season||d.seasons?.[0]||''
     setCurrentSeason(current)
     setSeason(current)
   }).catch(()=>{})
 },[])

 useEffect(()=>{
   setCompetition(null);setDivisao('');setFormato('')
   api<FiltersResponse>(`/api/rankings/filters?${query({country_id:country?.id})}`).then(d=>{
     setCompetitions(d.competitions)
     const nextSeasons=d.seasons||[]
     setSeasons(nextSeasons)
     const nextYears=(d.years&&d.years.length)?d.years:yearsFromSeasons(nextSeasons)
     setYears(nextYears)
     setDivisions(d.divisions||[])
     setFormats(d.formats||[])
     setDivisionFormats(d.division_formats||[])
     if(season && season!=='all' && d.seasons?.length && !d.seasons.includes(season)){
       setSeason(d.current_season||d.seasons[0]||'')
     }
     if(year!=='all' && nextYears.length && !nextYears.map(Number).includes(Number(year))){
       setYear('all')
     }
   }).catch(()=>{})
 },[country?.id])

 useEffect(()=>{
   api<FiltersResponse>(`/api/rankings/filters?${query({country_id:country?.id,competition_id:competition?.id})}`).then(d=>{
     setDivisions(d.divisions||[])
     setFormats(d.formats||[])
     setDivisionFormats(d.division_formats||[])
     setDivisao(v=>v&&!(d.divisions||[]).includes(v)?'':v)
     setFormato(v=>v&&!(d.formats||[]).includes(v)?'':v)
   })
 },[competition?.id,country?.id])

 useEffect(()=>{if(formato&&!formatsForDivision.includes(formato))setFormato('')},[formato,formatsForDivision])

 useEffect(()=>{
   if(!season)return
   let active=true
   setLoading(true)
   api<RankingResponse>(`/api/rankings?${query({metric:tab,country_id:country?.id,competition_id:competition?.id,season,year:year==='all'?undefined:year,min_games:minGames,venue,divisao:divisao||undefined,formato:formato||undefined})}`)
    .then(d=>{if(active)setData(d)})
    .finally(()=>{if(active)setLoading(false)})
   return()=>{active=false}
 },[tab,country?.id,competition?.id,season,year,minGames,venue,divisao,formato])

 useEffect(()=>{
   setSortKey(null)
   setSortDirection('desc')
 },[tab])

 const isPerformance=useMemo(()=>['5','10','20','season','history'].includes(tab),[tab])
 const isGoalRanking=useMemo(()=>['over15','over25','btts'].includes(tab),[tab])
 const isSofa=useMemo(()=>SOFASCORE_KEYS.has(tab),[tab])
 const isGoalsResult=useMemo(()=>GOALS_RESULT_KEYS.has(tab),[tab])
 const metricLabel=TABS.find(x=>x.key===tab)?.label||''
 const displayMetricLabel=season==='all'&&tab==='elo'?'ELO médio':season==='all'&&tab==='market'?'Valor de mercado acumulado':metricLabel
 const metricDecimals=data.decimals??(tab==='elo'?1:tab==='offense'||tab==='defense'?2:1)

 const fallbackColumns:ColumnDef[]=useMemo(()=>{
   const main:ColumnDef={key:'valor',label:displayMetricLabel,role:'main',decimals:metricDecimals,format:tab==='market'?'money':'number',suffix:isGoalRanking||isPerformance?'':(data.unit==='%'?'%':'')}
   if(isPerformance||isGoalRanking){
     const cols:ColumnDef[]=[main]
     if(isGoalRanking)cols.push({key:'taxa',label:'% dos jogos',decimals:1,suffix:'%'})
     cols.push(
       {key:'mgm',label:'MGM',decimals:2},{key:'mgs',label:'MGS',decimals:2},
       {key:'jogos',label:'J',format:'int'},{key:'vitorias',label:'V',format:'int'},
       {key:'empates',label:'E',format:'int'},{key:'derrotas',label:'D',format:'int'},
       {key:'gols_marcados',label:'GM',format:'int'},{key:'gols_sofridos',label:'GS',format:'int'},
       {key:'saldo_gols',label:'SG',format:'signed'},
     )
     return cols
   }
   if(tab==='elo'||tab==='offense'||tab==='defense'||tab==='market'){
     return [main,{key:'mgm',label:'MGM',decimals:2},{key:'mgs',label:'MGS',decimals:2}]
   }
   return [main,{key:'jogos',label:'Jogos',format:'int'},{key:'mgm',label:'MGM',decimals:2},{key:'mgs',label:'MGS',decimals:2}]
 },[displayMetricLabel,metricDecimals,tab,isGoalRanking,isPerformance,data.unit])

 const columns=useMemo(()=>{
   if(data.columns?.length){
     return data.columns.map(c=>c.key==='valor'?{...c,label:displayMetricLabel}:c)
   }
   return fallbackColumns
 },[data.columns,displayMetricLabel,fallbackColumns])

 function formatCell(col:ColumnDef,r:any){
   const v=r[col.key]
   if(col.key==='valor'){
     if(tab==='market')return money(r.valor,r.moeda)
     if(tab==='elo')return fmt(r.valor,1)
     if(tab==='offense'||tab==='defense')return fmt(r.valor,2)
     if(isGoalRanking)return `${fmtInt(r.valor)} jogos`
     if(isPerformance)return `${fmt(r.valor,1)}%`
     if(isGoalsResult && data.unit==='%')return `${fmt(r.valor,col.decimals??1)}%`
     if(col.suffix==='%'||data.unit==='%')return `${fmt(r.valor,col.decimals??metricDecimals)}%`
     if(col.format==='int'||data.unit==='total')return fmtInt(r.valor)
     return fmt(r.valor,col.decimals??metricDecimals)
   }
   if(col.format==='int')return fmtInt(v)
   if(col.format==='signed')return fmtSignedInt(v)
   if(col.format==='money')return money(v,r.moeda)
   if(col.suffix==='%')return v===null||v===undefined?'—':`${fmt(v,col.decimals??1)}%`
   return fmt(v,col.decimals??2)
 }

 function valueForSort(r:any,key:string){
   if(key==='rank')return numeric(r.posicao)
   if(key==='club')return String(r.clube||'')
   if(key==='country')return String(r.pais||'')
   return numeric(r[key]) ?? String(r[key]??'')
 }

 function requestSort(key:string){
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
     if(av===null||av===undefined||av==='')return 1
     if(bv===null||bv===undefined||bv==='')return -1
     if(typeof av==='string'||typeof bv==='string'){
       return String(av).localeCompare(String(bv),'pt-BR',{sensitivity:'base',numeric:true})*dir
     }
     if(av===bv)return String(a.clube||'').localeCompare(String(b.clube||''),'pt-BR',{sensitivity:'base'})
     return (Number(av)-Number(bv))*dir
   })
 },[data.rows,sortKey,sortDirection])

 function SortHeader({sort,label,className}:{sort:string;label:string;className?:string}){
   const active=sortKey===sort
   return <th className={`sortable-ranking-th ${active?'active-sort':''} ${className||''}`}>
    <button type="button" onClick={()=>requestSort(sort)} title={`Ordenar por ${label}`}>
      <span>{label}</span>
      <span className="ranking-sort-icon" aria-hidden="true">{active?(sortDirection==='desc'?'▼':'▲'):'↕'}</span>
    </button>
   </th>
 }

 const clearFilters=()=>{
   setCountry(null);setCompetition(null);setSeason(currentSeason);setYear('all');setMinGames('5');setDivisao('');setFormato('');setVenue('all')
 }

 function selectSubject(id:string){
   const group=TAB_GROUPS.find(g=>g.id===id)
   if(!group)return
   setSubject(id)
   if(!group.tabs.some(t=>t.key===tab))setTab(group.tabs[0].key)
 }

 return <section className="page rankings-page">
  <div className="page-header"><div><span className="eyebrow">LEAGUE INTELLIGENCE</span><h1>Rankings</h1><p>Compare os clubes por rating, força, mercado, gols, desempenho e estatísticas SofaScore.</p></div></div>

  <div className="rankings-sticky">
   <div className="panel rankings-filter-bar">
    <IdAutocomplete label="País" value={country} options={countries} onChange={setCountry} placeholder="Todos os países"/>
    <IdAutocomplete label="Campeonato" value={competition} options={competitions} onChange={setCompetition} placeholder="Todos os campeonatos"/>
    <div className="field"><label>Temporada</label><select value={season} onChange={e=>setSeason(e.target.value)}><option value="all">Todas as temporadas</option>{seasons.map(s=><option key={s} value={s}>{s}</option>)}</select></div>
    <div className="field"><label>Ano</label><select value={year} onChange={e=>setYear(e.target.value)}><option value="all">Todos os anos</option>{yearOptions.map(y=><option key={y} value={y}>{y}</option>)}</select></div>
    <div className="field"><label>Mín. jogos</label><select value={minGames} onChange={e=>setMinGames(e.target.value)}>{MIN_GAMES_OPTIONS.map(n=><option key={n} value={n}>{n}</option>)}</select></div>
    <div className="field"><label>Divisão</label><select value={divisao} onChange={e=>setDivisao(e.target.value)}><option value="">Todas as divisões</option>{divisions.map(v=><option key={v} value={v}>{v}</option>)}</select></div>
    <div className="field"><label>Formato</label><select value={formato} onChange={e=>setFormato(e.target.value)}><option value="">Todos os formatos</option>{formatsForDivision.map(v=><option key={v} value={v}>{v}</option>)}</select></div>
    <div className="field"><label>Mando de campo</label><select value={venue} onChange={e=>setVenue(e.target.value)}><option value="all">Todos</option><option value="home">Mandante</option><option value="away">Visitante</option></select></div>
    <button className="secondary rankings-clear" onClick={clearFilters}>Limpar filtros</button>
   </div>

   <div className="rankings-subject-tabs" role="tablist" aria-label="Assuntos do ranking">
    {TAB_GROUPS.map(group=>(
     <button key={group.id} type="button" role="tab" aria-selected={subject===group.id}
      className={subject===group.id?'active':''} onClick={()=>selectSubject(group.id)}>{group.title}</button>
    ))}
   </div>

   <div className="rankings-metric-chips" role="tablist" aria-label={`Métricas · ${activeGroup.title}`}>
    {activeGroup.tabs.map(t=>(
     <button key={t.key} type="button" className={tab===t.key?'active':''} onClick={()=>setTab(t.key)}>{t.label}</button>
    ))}
   </div>
  </div>

  {data.warning&&<div className="notice info">{data.warning}</div>}
  {(tab==='elo'||tab==='market')&&venue!=='all'&&<div className="notice info">O mando é aplicado às médias de gols exibidas, mas não altera {tab==='elo'?'o ELO':'o valor de mercado'}.</div>}
  {season==='all'&&!isSofa&&!isGoalsResult&&<div className="notice info">Todas as temporadas: o histórico é consolidado em um único ranking. No ELO, o valor principal é a média dos ELOs finais por temporada.</div>}
  {isSofa&&<div className="notice info">Fonte: tabela jogo_completo (SofaScore). Exige pelo menos {minGames} jogos com a métrica no recorte. {(data.lower_is_better||tab==='shots_per_goal'||tab==='sot_per_goal')?'Menor valor = mais eficiente.':''}</div>}
  {isGoalsResult&&<div className="notice info">Fonte: jogos + minutos_gols. Exige pelo menos {minGames} jogos com sequência completa no recorte. Faixas: acréscimos do 1º tempo entram em 31-45.</div>}

  <div className="panel rankings-panel">
   <div className="panel-title"><div><h2>{displayMetricLabel}</h2><span>{data.rows.length.toLocaleString('pt-BR')} clubes no recorte · {season==='all'?'Todas as temporadas':season}{year!=='all'?` · ${year}`:''}{(divisao||formato)?` · ${[divisao||'Todas divisões',formato||'Todos formatos'].join(' · ')}`:''}</span></div>{(tab==='defense'||data.lower_is_better)&&<span>Menor índice = melhor</span>}</div>
   {loading?<div className="empty-state">Calculando ranking...</div>:<div className="table-scroll"><table className="rankings-table"><thead><tr>
    <SortHeader sort="rank" label="#"/>
    <SortHeader sort="club" label="Clube"/>
    <SortHeader sort="country" label="País"/>
    {columns.map(col=>(
      <SortHeader key={col.key} sort={col.key} label={col.label} className={col.role==='main'?'ranking-main-col':''}/>
    ))}
   </tr></thead><tbody>{sortedRows.map((r:any,index:number)=><tr key={`${r.clube_id}-${r.campeonato_id||''}-${r.moeda||''}-${index}`}>
    <td><span className={`rank-position ${index<3?'top':''}`}>{sortKey?index+1:r.posicao}</span></td>
    <td><div className="club-inline">{r.escudo_url?<img src={r.escudo_url}/>:<span className="mini-crest">{String(r.clube||'?')[0]}</span>}<strong>{r.clube}</strong></div></td>
    <td>{r.pais||'—'}</td>
    {columns.map(col=>(
      <td key={col.key} className={col.role==='main'?'ranking-main-cell':''}>
       {col.role==='main'?<strong className="ranking-main-value">{formatCell(col,r)}</strong>:formatCell(col,r)}
       {col.key==='valor'&&tab==='market'&&<small className="ranking-currency">{r.moeda}</small>}
      </td>
    ))}
   </tr>)}</tbody></table></div>}
   {!loading&&!data.rows.length&&<div className="empty-state">Nenhum clube com dados suficientes para este recorte.</div>}
  </div>
 </section>
}
