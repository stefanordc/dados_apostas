import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import IdAutocomplete from '../components/IdAutocomplete'
import ClubStatisticsPanel from '../components/ClubStatisticsPanel'

type Item = { id: number; nome: string; [key:string]:unknown }
type Market = {key:string;name:string;kind:'back'|'lay';games:number;wins:number;losses:number;rate:number|null;breakeven_odd:number|null;breakeven_type:'min'|'max';settled:number;unpriced:number;profit:number|null;stakes:number|null;avg_odd:number|null;years:Record<string,YearItem>}
type MonthItem = {month:string; games:number;wins:number;settled:number;profit:number|null;stakes:number|null}
type YearItem = {games:number;wins:number;settled:number;profit:number|null;stakes:number|null;months:MonthItem[]}
type Annual = {year:number;values:Record<string,YearItem>}
type Score = {score:string;games:number;percentage:number}
type StrategyMetrics = {games:number;wins:number;losses:number;win_rate:number|null;fair_lay_odd:number|null;profit:number|null;roi:number|null}
type StrategyRange = {odd_min:number;odd_max:number;kind:'observed_profit'|'historical_frequency';period_initial:string;period_final:string;training:StrategyMetrics;validation:StrategyMetrics;total:StrategyMetrics}
type StrategyMarket = {key:string;label:string;reference_label:string;filter_key:string;kind:'observed_profit'|'historical_frequency';reference_games:number;quoted_games:number;suggestions:StrategyRange[]}
type StrategyData = {markets:StrategyMarket[];default_market:string|null;min_priced_sample:number;explanation:string}
type LeagueOverview = {games:number;goals:number;avg_goals:number|null;home_wins:number;draws:number;away_wins:number;home_rate:number|null;draw_rate:number|null;away_rate:number|null;over25_rate:number|null;btts_rate:number|null}
type TrendMetrics = {games:number;wins:number;losses:number;win_rate:number|null}
type TrendData = {markets:{key:string;label:string;initial:TrendMetrics;posterior:TrendMetrics;total:TrendMetrics;period_start:string|null;period_end:string|null}[];explanation:string}
type LeagueCompareItem = {competition_id:number|null;competition:string;country:string;games:number;wins:number;losses:number;win_rate:number|null;profit:number|null;roi:number|null;settled:number}
type LeagueCompareMarket = {key:string;label:string;items:LeagueCompareItem[]}
type LeagueComparison = {total_leagues:number;markets:LeagueCompareMarket[];explanation:string}
type LeagueMarketYear = {year:number;games:number;wins:number;losses:number;win_rate:number|null;settled:number;profit:number|null;roi:number|null}
type LeagueMarketHistory = {country:string;competition:string;market:string;market_label:string;use_odds:boolean;year_from:number;year_to:number;years:LeagueMarketYear[];total:{games:number;wins:number;losses:number;win_rate:number|null}}
type LeagueSelection = {country:string;competition:string;market:string}
type Data = {year_from?:number|null;year_to?:number|null;use_odds:boolean;data_source:'historico_jogos'|'historico_odds';historical_trends?:TrendData;league_overview?:LeagueOverview;league_comparison?:LeagueComparison;odds_suggestions?:StrategyData;tab:string; divisao:string|null;formato:string|null;markets:Record<string,Market>;annual:Annual[];years:number[];games:number;club:string|null;opponent:string|null;stake:number;start_season:string;explanation:string;odds_audit?:{markets:{key:string;label:string}[];default_market:string|null;games:Record<string,AuditGame[]>};odds_reconciliation?:{pending_clubs?:number;status:string;database:string|null;odds_rows:number;matched_games:number;ambiguous_games:number;unmatched_games:number;legacy_only_games:number;without_any_odds:number;games_total:number};scores?:{total:number;scores:Score[]};head_to_head?:{games:number;markets:Record<string,Market>;annual:Annual[];scores:{total:number;scores:Score[]}}}
type AuditGame = {date:string;season:string;divisao:string|null;formato:string|null;home:string;away:string;score:string;odd:number|null;green:boolean;priced:boolean;profit:number|null;cumulative_rate:number;cumulative_games:number}
type ClubPending = {historico_jogos:string;historico_odds:string;posicao:'casa'|'fora';ocorrencias:number;exemplo_data:string;exemplo_jogo:string;exemplo_odds:string;confianca:'alta'|'verificar'}
type OddFixtureCandidate = {odds_casa:string;odds_fora:string}
type UnresolvedFixture = {data:string;temporada:string;jogos_casa:string;jogos_fora:string;candidatos:OddFixtureCandidate[]}
type ConciliationResponse = {competition_id:number;pending_count:number;pending:ClubPending[];unresolved:UnresolvedFixture[]}
type Bounds = Record<string,string>

const tabs = [
 {key:'league',name:'Estatísticas por Campeonato'},
 {key:'goals',name:'Gols e Resultado'},
 {key:'club_stats',name:'Estatísticas por Clube'},
 {key:'team',name:'Resultado por Time'},
 {key:'mo_home',name:'MO Casa'},
 {key:'mo_away',name:'MO Fora'},
 {key:'lay_home',name:'Lay Casa'},
 {key:'lay_away',name:'Lay Fora'},
 {key:'lay_big_home',name:'Lay Goleada Casa'},
 {key:'lay_big_away',name:'Lay Goleada Fora'},
 {key:'scores',name:'Correct Score'},
] as const
type GoalCardStat = {key:string;label:string;note:string;value:number|null;count:number;total:number}
type GoalBand = {label:string;value:number|null;count:number;total:number}
type GoalsData = {games:number;valid_games:number;requested_games:number;goals_recorded:number;truncated:boolean;cards:GoalCardStat[];minute_bands:GoalBand[];warning:string|null;denominators:string;year_from:number|null;year_to:number|null;continent:string|null;country:string|null;competition:string|null}
const marketLabels:Record<string,string> = {
 back_home:'MO Casa',lay_home:'Lay Casa',draw:'Empate',back_away:'MO Fora',lay_away:'Lay Fora',
 over05:'Over 0,5',over15:'Over 1,5',over25:'Over 2,5',under35:'Under 3,5',btts:'Ambos marcam',
 lay_big_home:'Lay goleada Casa',lay_big_away:'Lay goleada Fora'
}
const oddsGroups = [{key:'mo',name:'Match Odds (MO)'},{key:'over05',name:'Over 0,5'},{key:'over15',name:'Over 1,5'},{key:'over25',name:'Over 2,5'},{key:'under35',name:'Under 3,5'},{key:'btts',name:'Ambos marcam'}]
const initialBounds:Bounds = Object.fromEntries(oddsGroups.flatMap(g=>[[g.key+'_min',''],[g.key+'_max','']]))
const n=(v:number|null|undefined,dec=1)=>v==null?'—':v.toLocaleString('pt-BR',{minimumFractionDigits:dec,maximumFractionDigits:dec})
const integer=(v:number|null|undefined)=>v==null?'—':v.toLocaleString('pt-BR')
const money=(v:number|null|undefined)=>v==null?'—':v.toLocaleString('pt-BR',{style:'currency',currency:'BRL'})
const signed=(v:number|null|undefined)=>v==null?'—':`${v>0?'+':''}${n(v,2)}`
const shortMonth=(s:string)=>{const [y,m]=s.split('-');return `${m}/${y}`}
const itemNames=(names:string[]):Item[]=>names.map((name,index)=>({id:index+1,nome:name}))

const cardOrder = ['back_home','lay_home','draw','back_away','lay_away','over05','over15','over25','under35','btts','lay_big_home','lay_big_away']
// Um único conjunto de dados atende todas as subabas do campeonato.
const leagueSubtabs = [
 {key:'general',name:'Geral'},
 ...[
  'back_home','back_away','draw','lay_home','lay_away',
  'lay_big_home','lay_big_away','over05','over15','over25',
  'under35','btts',
 ].map(key=>({key,name:marketLabels[key]})),
 {key:'scores',name:'Placar exato'},
]
function Cards({markets,focus,useOdds}:{markets:Record<string,Market>;focus:string;useOdds:boolean}) {
 // As 12 métricas ficam sempre visíveis, em ordem fixa, em todas as abas.
 // A aba selecionada muda apenas o destaque, não o conjunto de cards.
 const sorted = cardOrder.map(key=>markets[key]).filter((value):value is Market=>Boolean(value))
 return <div className="bt-metrics">{sorted.map(m=><div className={`bt-metric ${m.key===focus?'selected':''}`} key={m.key}>
   <div className="bt-metric-title"><span>{m.name}</span><small>{m.kind==='lay'?'LAY':'BACK'}</small></div>
   <div className="bt-metric-value">{m.rate==null?'—':`${n(m.rate)}%`}</div>
   {!useOdds&&<div className="bt-metric-count">Win Rate (sem odds)</div>}
   <div className="bt-metric-count">{integer(m.wins)} / {integer(m.games)} jogos favoráveis</div>
   <div className="bt-progress"><span style={{width:`${Math.max(0,Math.min(m.rate||0,100))}%`}}/></div>
   <div className="bt-metric-foot"><span>{useOdds?`Odd ${m.breakeven_type==='max'?'máxima Lay':'mínima Back'} para equilíbrio`:'Acertos / Erros'}</span><strong>{useOdds?(m.breakeven_odd==null?'—':n(m.breakeven_odd,2)):`${integer(m.wins)} / ${integer(m.losses)}`}</strong></div>
   {useOdds&&m.settled>0&&<div className="bt-metric-profit">L/P observado: <strong className={(m.profit||0)>=0?'positive':'negative'}>{money(m.profit)}</strong></div>}
   {useOdds&&!m.settled&&<div className="bt-metric-unpriced">Sem odds compatíveis para calcular L/P</div>}
  </div>)}</div>
}
function GoalsResultPanel({data}:{data:GoalsData}) {
 const season=`${data.year_from||'Início'} a ${data.year_to||'Hoje'}`
 const maxBand=Math.max(1,...data.minute_bands.map(b=>b.value||0))
 return <div className="bt-goals-panel">
  <section className="bt-league-overview" aria-label="Cobertura da linha do tempo">
   <div className="bt-league-overview-head"><h3>Gols e Resultado · {season}</h3>
    <span>{integer(data.valid_games)} / {integer(data.requested_games)} partidas com sequência válida · {integer(data.goals_recorded)} gols</span></div>
   {data.warning&&<p className="bt-error" role="status">{data.warning}</p>}
   {data.truncated&&<p className="bt-note" role="status">Amostra truncada nas partidas mais recentes do recorte.</p>}
  </section>
  <section className="bt-section-title"><div><span className="bt-eyebrow">ABERTURA DO PLACAR</span><h2>Comportamento após o primeiro gol</h2><p>{data.denominators}</p></div></section>
  <div className="bt-metrics bt-goals-cards">{data.cards.map(card=><div className="bt-metric" key={card.key}>
   <div className="bt-metric-title"><span>{card.label}</span></div>
   <div className="bt-metric-value">{card.value==null?'—':`${n(card.value)}%`}</div>
   <div className="bt-metric-count">{integer(card.count)} / {integer(card.total)}</div>
   <div className="bt-progress"><span style={{width:`${Math.max(0,Math.min(card.value||0,100))}%`}}/></div>
   <div className="bt-metric-foot"><span>{card.note}</span></div>
  </div>)}</div>
  <section className="bt-annual-panel bt-goals-bands">
   <div className="bt-annual-title"><div><h3>Gols por minuto</h3><span>Distribuição percentual dos gols validados nas faixas pedidas (acréscimos do 1º tempo em 31–45).</span></div></div>
   <div className="bt-goals-columns" role="img" aria-label="Gráfico de colunas com a distribuição percentual de gols por faixa de minuto">
    {data.minute_bands.map(band=>{
     const height=Math.max(band.value==null?0:4,((band.value||0)/maxBand)*100)
     return <div className="bt-goals-column" key={band.label}>
      <strong className="bt-goals-column-value">{band.value==null?'—':`${n(band.value)}%`}</strong>
      <div className="bt-goals-column-track" aria-hidden="true"><span style={{height:`${height}%`}}/></div>
      <strong className="bt-goals-column-label">{band.label}</strong>
      <small>{integer(band.count)} / {integer(band.total)}</small>
     </div>
    })}
   </div>
  </section>
 </div>
}

function LeagueOverviewPanel({data,season}:{data:LeagueOverview;season:string}) {
 const stats=[
  {label:'Partidas',value:integer(data.games),detail:'Jogos encerrados'},
  {label:'Gols marcados',value:integer(data.goals),detail:`${n(data.avg_goals,2)} por jogo`},
  {label:'Vitórias mandantes',value:integer(data.home_wins),detail:`${n(data.home_rate)}% dos jogos`},
  {label:'Empates',value:integer(data.draws),detail:`${n(data.draw_rate)}% dos jogos`},
  {label:'Vitórias visitantes',value:integer(data.away_wins),detail:`${n(data.away_rate)}% dos jogos`},
  {label:'Over 2,5',value:data.over25_rate==null?'—':`${n(data.over25_rate)}%`,detail:'Frequência de 3+ gols'},
  {label:'Ambas marcam',value:data.btts_rate==null?'—':`${n(data.btts_rate)}%`,detail:'Frequência observada'},
 ]
 return <section className="bt-league-overview" aria-label="Resumo da temporada">
  <div className="bt-league-overview-head"><h3>Resumo das partidas · {season}</h3><span>Somente jogos finalizados do recorte selecionado</span></div>
  <div className="bt-league-stats">{stats.map(stat=><div key={stat.label} className="bt-league-stat"><small>{stat.label}</small><strong>{stat.value}</strong><span>{stat.detail}</span></div>)}</div>
 </section>
}

function LeagueComparisonPanel({data,marketKey,useOdds,divisao,formato,appliedBounds}:{data:LeagueComparison;marketKey:string;useOdds:boolean;divisao:string|null;formato:string|null;appliedBounds:Bounds}) {
 const [showAll,setShowAll]=useState(false)
 const [selected,setSelected]=useState<LeagueSelection|null>(null)
 const [history,setHistory]=useState<LeagueMarketHistory|null>(null)
 const [historyLoading,setHistoryLoading]=useState(false)
 const [historyError,setHistoryError]=useState('')
 const selectedMarket=data.markets.find(item=>item.key===marketKey)
 const chosenMarkets=selectedMarket?[selectedMarket]:[]
 const maxLeagues=selectedMarket?.items.length||0
 const selectedKey=selected?`${selected.market}__${selected.country}__${selected.competition}`:null
 const oddsParams=Object.fromEntries(Object.entries(appliedBounds).map(([key,value])=>[key,value.trim()?Number(value.replace(',','.')):null]))
 useEffect(()=>{
  if(!selected){setHistory(null);setHistoryError('');setHistoryLoading(false);return}
  let active=true
  const controller=new AbortController()
  const timeout=window.setTimeout(()=>controller.abort(),45000)
  setHistory(null);setHistoryError('');setHistoryLoading(true)
  api<LeagueMarketHistory>('/api/backtesting/league-market-history',{
    method:'POST',signal:controller.signal,
    body:JSON.stringify({country:selected.country,competition:selected.competition,market:selected.market,
      use_odds:useOdds,divisao,formato,...(useOdds?oddsParams:{})}),
  }).then(result=>{if(active)setHistory(result)})
    .catch((error:Error)=>{if(active)setHistoryError(controller.signal.aborted?'Tempo de consulta excedido. Tente novamente.':error.message)})
    .finally(()=>{window.clearTimeout(timeout);if(active)setHistoryLoading(false)})
  return ()=>{active=false;window.clearTimeout(timeout);controller.abort()}
 },[selectedKey,useOdds,divisao,formato,JSON.stringify(oddsParams)])
 const toggle=(market:string,item:LeagueCompareItem)=>{
  const key=`${market}__${item.country}__${item.competition}`
  setSelected(selectedKey===key?null:{market,country:item.country,competition:item.competition})
 }
 return <section className="bt-league-compare">
  <div className="bt-league-overview-head"><h3>{marketLabels[marketKey]||selectedMarket?.label||"Mercado"} — comparação entre campeonatos</h3><span>{integer(data.total_leagues)} campeonatos no recorte · Win Rate</span></div>
  <p className="bt-note">Clique em um campeonato para abrir os últimos 10 anos daquele mercado, de forma independente do intervalo De/Até do comparativo.</p>
  {maxLeagues>24&&<button type="button" className="bt-secondary" onClick={()=>setShowAll(v=>!v)}>{showAll?'Exibir 24 ligas por mercado':`Exibir todas as ${integer(maxLeagues)} ligas por mercado`}</button>}
  <div className="bt-compare-grid bt-compare-single">
   {chosenMarkets.map(market=>{
    const items=market.items
    const top=showAll?items:items.slice(0,Math.min(items.length,24))
    const maxRate=Math.max(1,...top.map(item=>item.win_rate||0))
    return <div key={market.key} className="bt-compare-card">
      <div className="bt-compare-head"><h4>{marketLabels[market.key]||market.label}</h4><span>{integer(items.length)} ligas</span></div>
      {top.length?<div className="bt-compare-bars">
        {top.map(item=>{
          const open=selectedKey===`${market.key}__${item.country}__${item.competition}`
          return <Fragment key={`${market.key}-${item.country}-${item.competition}`}>
            <button type="button" className={`bt-compare-row bt-compare-trigger ${open?'is-selected':''}`}
              aria-expanded={open} aria-label={`Ver últimos 10 anos de ${item.competition} em ${market.label}`}
              onClick={()=>toggle(market.key,item)}>
              <span className="bt-compare-labels"><strong>{item.competition}</strong><small>{item.country} · {integer(item.games)} jogos</small></span>
              <span className="bt-compare-bar"><span style={{width:`${Math.max(2,((item.win_rate||0)/maxRate)*100)}%`}}/></span>
              <span className="bt-compare-value">{item.win_rate==null?'—':`${n(item.win_rate)}%`}</span>
            </button>
            {open&&<div className="bt-compare-detail" role="region" aria-label={`Histórico de ${item.competition} em ${market.label}`}>
              <div className="bt-compare-detail-head"><div><strong>{item.competition} · {market.label}</strong><small>Últimos 10 anos-calendário (ano atual parcial) · {useOdds?'jogos com odds conciliadas':'historico_jogos'}</small></div><button type="button" className="bt-quiet" onClick={()=>setSelected(null)}>Fechar</button></div>
              {historyLoading&&<p role="status" className="bt-note">Carregando histórico...</p>}
              {historyError&&<p role="alert" className="bt-error">{historyError}</p>}
              {history&&!historyLoading&&<>
                <div className="bt-compare-year-bars">
                {history.years.map(y=><div className="bt-compare-year" key={y.year} title={`${y.year}: ${integer(y.wins)} acertos, ${integer(y.losses)} erros, ${integer(y.games)} jogos`}>
                  <strong>{y.year}</strong><div className="bt-compare-year-track"><span style={{width:`${y.win_rate||0}%`}}/></div>
                  <strong>{y.win_rate==null?'—':`${n(y.win_rate)}%`}</strong><small>{integer(y.games)} jogos · {integer(y.wins)}G/{integer(y.losses)}R</small>
                  {useOdds&&<small>{y.roi==null?'ROI —':`ROI ${n(y.roi)}%`}</small>}
                </div>)}
                </div>
                <p className="bt-compare-total">Total: {integer(history.total.games)} jogos · {integer(history.total.wins)} acertos · {integer(history.total.losses)} erros · WR {history.total.win_rate==null?'—':`${n(history.total.win_rate)}%`}</p>
              </>}
            </div>}
          </Fragment>
        })}
       </div>:<div className="bt-empty-inline">Nenhuma liga gerou amostra para este mercado.</div>}
    </div>
   })}
  </div>
 </section>
}

function ScoreTable({rows,total}:{rows:Score[];total:number}) {
 return <div className="bt-score-panel">
  <div className="bt-score-title"><h3>Placar exato</h3><span>{integer(total)} jogos analisados · Casa × Fora</span></div>
  <div className="bt-score-table"><table><thead><tr><th>Pos.</th><th>Placar</th><th>Jogos</th><th>Proporção</th><th>Distribuição</th></tr></thead><tbody>
   {rows.map((r,i)=><tr key={r.score}><td>{i+1}</td><td><strong>{r.score}</strong></td><td>{integer(r.games)}</td><td>{n(r.percentage)}%</td><td><div className="bt-score-bar"><span style={{width:`${Math.min(r.percentage,100)}%`}}/></div></td></tr>)}
  </tbody></table></div>
 </div>
}
// A ordem abaixo também é utilizada na linha de totais.
const settledKeys = ['back_home','back_away','lay_home','lay_away','lay_big_home','lay_big_away','over15','over25','btts']

function AnnualTable({annual,markets,years,focus,caption,seasonMode=false,useOdds=true}:{annual:Annual[];markets:Record<string,Market>;years:number[];focus:string;caption:string;seasonMode?:boolean;useOdds?:boolean}){
 const cols = settledKeys
 const [openYears,setOpenYears]=useState<number[]>([])
 const toggle=(yr:number)=>setOpenYears(v=>v.includes(yr)?v.filter(y=>y!==yr):[...v,yr])
 if (!useOdds) {
  const rate=(wins:number,count:number)=>count?`${n(wins/count*100)}%`:'—'
  const annualYear=(year:Annual,key:string)=>year.values[key]
  const combined=(year?:Annual,month?:string)=>{
   const records=year?[year]:annual
   let wins=0,games=0
   for (const row of records) for (const key of settledKeys) {
    const item=row.values[key]
    const value=month?item?.months.find(m=>m.month===month):item
    wins+=value?.wins||0;games+=value?.games||0
   }
   return rate(wins,games)
  }
  const overall=(key:string)=>rate(annual.reduce((a,y)=>a+(annualYear(y,key)?.wins||0),0),annual.reduce((a,y)=>a+(annualYear(y,key)?.games||0),0))
  return <div className="bt-annual-panel bt-winrate-panel">
   <div className="bt-annual-title"><div><h3>{caption}</h3><span>{seasonMode?'Somente a temporada escolhida':'Anos-calendário · histórico de partidas'} · Resultado em Win Rate (%)</span></div><span className="bt-tag">Clique no ano para expandir</span></div>
   <div className="bt-table"><table><thead><tr><th>Ano</th><th>Jogos</th>{settledKeys.map(key=><th key={key}>{marketLabels[key]||key} <small>Win Rate</small></th>)}<th>WR combinado*</th></tr></thead><tbody>
    {annual.map(year=>{
     const open=openYears.includes(year.year)
     const months=Array.from(new Set(settledKeys.flatMap(k=>(annualYear(year,k)?.months||[]).map(m=>m.month)))).sort()
     const yearGames=Math.max(0,...settledKeys.map(k=>annualYear(year,k)?.games||0))
     return <Fragment key={year.year}>
      <tr className="bt-year-row" onClick={()=>toggle(year.year)} aria-expanded={open}><td><strong>{open?'▾':'▸'} {year.year}</strong></td><td>{integer(yearGames)}</td>
       {settledKeys.map(key=>{const item=annualYear(year,key);return <td key={key} title={`${integer(item?.wins)} acertos em ${integer(item?.games)} jogos`}>{rate(item?.wins||0,item?.games||0)}</td>})}
       <td><strong>{combined(year)}</strong></td></tr>
      {open&&months.map(month=><tr className="bt-month-row" key={`${year.year}-${month}`}><td>↳ {shortMonth(month)}</td><td>{integer(Math.max(0,...settledKeys.map(k=>annualYear(year,k)?.months.find(m=>m.month===month)?.games||0)))}</td>
       {settledKeys.map(key=>{const item=annualYear(year,key)?.months.find(m=>m.month===month);return <td key={key} title={`${integer(item?.wins)} acertos em ${integer(item?.games)} jogos`}>{rate(item?.wins||0,item?.games||0)}</td>})}
       <td>{combined(year,month)}</td></tr>)}
     </Fragment>
    })}
    <tr className="bt-total-row"><td><strong>TOTAL ({annual.length} ANOS)</strong></td><td><strong>{integer(annual.reduce((acc,y)=>acc+Math.max(0,...settledKeys.map(k=>y.values[k]?.games||0)),0))}</strong></td>
     {settledKeys.map(key=><td key={key}><strong>{overall(key)}</strong></td>)}<td><strong>{combined()}</strong></td></tr>
   </tbody></table></div>
   <p className="bt-note">* WR combinado = acertos / ocorrências somadas dos mercados exibidos. Uma partida pode participar de vários mercados; portanto, o WR combinado não é a taxa de uma única estratégia. Os totais de cada coluna são ponderados pela quantidade de jogos, não médias simples dos percentuais. Sem odds não há stakes, unidades, ROI ou lucro.</p>
  </div>
 }

 function yearValue(y:Annual,key:string):YearItem|undefined {return y.values[key]}
 // Um mercado sem cotação real é nulo, não zero. Zero só é possível quando há aposta liquidada.
 function sumQuoted(values:(number|null|undefined)[]):number|null {
  const valid=values.filter((v):v is number=>typeof v==='number'&&Number.isFinite(v))
  return valid.length ? Math.round(valid.reduce((a,b)=>a+b,0)*100)/100 : null
 }
 const yearProfit=(year:Annual,month?:string)=>sumQuoted(cols.map(key=>{
  const data=yearValue(year,key)
  return month?data?.months.find(m=>m.month===month)?.profit:data?.profit
 }))
 const totals=Object.fromEntries(cols.map(key=>[key,sumQuoted(annual.map(year=>yearValue(year,key)?.stakes))])) as Record<string,number|null>
 const totalProfit=sumQuoted(annual.map(year=>yearProfit(year)))
 const totalPricedGames=annual.reduce((sum,year)=>sum+Math.max(0,...cols.map(key=>yearValue(year,key)?.settled||0)),0)
 const layGoleada = (key:string)=>key==='lay_big_home'||key==='lay_big_away'
 const winRate = (wins:number,games:number)=>games ? `${n(wins/games*100)}% (Win Rate)` : '—'
 const shownValue=(key:string,data:YearItem|MonthItem|undefined)=>{
   if (data?.stakes!=null) return signed(data.stakes)
   if (layGoleada(key)&&data?.games) return winRate(data.wins,data.games)
   return '—'
 }
 const totalShownValue=(key:string)=>{
   if(totals[key]!=null) return signed(totals[key])
   if(!layGoleada(key)) return '—'
   const games=annual.reduce((sum,year)=>sum+(yearValue(year,key)?.games||0),0)
   const wins=annual.reduce((sum,year)=>sum+(yearValue(year,key)?.wins||0),0)
   return winRate(wins,games)
 }
 const financialClass=(value:number|null|undefined)=>value==null?'':value<0?'negative':value>0?'positive':''
 return <div className="bt-annual-panel">
  <div className="bt-annual-title"><div><h3>{caption}</h3><span>{seasonMode?'Resultado em stakes de R$ 100,00 · apenas jogos da temporada selecionada':'Resultado em stakes de R$ 100,00 · anos-calendário, independente da temporada inicial'}</span></div><span className="bt-tag">Clique no ano para expandir</span></div>
  <div className="bt-table"><table><thead><tr><th>Ano</th><th>Jogos com odds</th>{cols.map(key=><th key={key}>{marketLabels[key]||key} <small>({layGoleada(key)?'stakes / Win Rate':'stakes'})</small></th>)}<th>L/P somado*</th></tr></thead><tbody>
   {annual.map(year=>{
    const open=openYears.includes(year.year)
    const pricedGames=Math.max(0,...cols.map(key=>yearValue(year,key)?.settled||0))
    const uniqueMonths = Array.from(new Set(cols.flatMap(k=>(yearValue(year,k)?.months||[]).map(m=>m.month)))).sort()
    return <Fragment key={year.year}>
      <tr className="bt-year-row" onClick={()=>toggle(year.year)} aria-expanded={open}><td><strong>{open?'▾':'▸'} {year.year}</strong></td><td>{integer(pricedGames)}</td>
      {cols.map(key=><td className={financialClass(yearValue(year,key)?.stakes)} key={key} title={key.startsWith('lay_')&&yearValue(year,key)?.stakes==null?'Sem cotação Lay: indicador de win rate quando disponível':undefined}>{shownValue(key,yearValue(year,key))}</td>)}
      <td className={financialClass(yearProfit(year))}><strong>{money(yearProfit(year))}</strong></td></tr>
      {open&&uniqueMonths.map(month=><tr className="bt-month-row" key={`${year.year}-${month}`}><td>↳ {shortMonth(month)}</td><td>{integer(Math.max(0,...cols.map(k=>yearValue(year,k)?.months.find(m=>m.month===month)?.settled||0)))}</td>
       {cols.map(key=>{const value=yearValue(year,key)?.months.find(x=>x.month===month)?.stakes;return <td key={key} className={financialClass(value)}>{shownValue(key,yearValue(year,key)?.months.find(x=>x.month===month))}</td>})}
       <td className={financialClass(yearProfit(year,month))}>{money(yearProfit(year,month))}</td></tr>)}
      </Fragment>
   })}
   <tr className="bt-total-row"><td><strong>TOTAL ({annual.length} ANOS)</strong></td><td><strong>{integer(totalPricedGames)}</strong></td>
    {cols.map(key=><td key={key} className={financialClass(totals[key])} title={`${marketLabels[key]||key} · total no período`}><strong>{totalShownValue(key)}</strong></td>)}
    <td className={financialClass(totalProfit)}><strong>{money(totalProfit)}</strong></td>
   </tr>
   </tbody></table></div>
  <p className="bt-note">* Soma dos mercados com odds registradas; a mesma partida pode gerar mais de uma entrada. Os totais dos mercados cotados estão em stakes (1 stake = R$ 100,00); o L/P somado já está em reais e não é multiplicado novamente. Nas colunas Lay Goleada sem odd, WR = win rate (acertos / jogos), inclusive no TOTAL ponderado por jogos. WR não entra na soma monetária. Quando existir odd Lay real, exibimos stakes liquidadas. “—” significa cotação ausente, não resultado zero. Mercados Lay não são liquidados com odds Back.</p>
 </div>
}


function ClubConciliation({pending,onSave}:{pending:ClubPending[];onSave:(item:ClubPending,standard:string)=>Promise<void>}) {
 const [expanded,setExpanded]=useState<string|null>(null)
 const [choice,setChoice]=useState('jogos')
 const [custom,setCustom]=useState('')
 const [saving,setSaving]=useState(false)
 const [error,setError]=useState('')
 const [confirmed,setConfirmed]=useState(false)
 const [visible,setVisible]=useState(20)
 const keyOf=(x:ClubPending)=>`${x.posicao}::${x.historico_jogos}::${x.historico_odds}`
 const selected=pending.find(item=>keyOf(item)===expanded)
 const standard=selected ? choice==='jogos'?selected.historico_jogos:choice==='odds'?selected.historico_odds:custom.trim() : ''
 const toggle=(item:ClubPending)=>{
   const next=keyOf(item)
   setExpanded(old=>old===next?null:next)
   setChoice('jogos');setCustom('');setError('');setConfirmed(false)
 }
 const submit=async()=>{
   if(!selected || !standard.trim() || (selected.confianca==='verificar'&&!confirmed)) {
     setError('Informe o nome padrão e confirme que os clubes são equivalentes.');return
   }
   setSaving(true);setError('')
   try{await onSave(selected,standard.trim());setExpanded(null);setChoice('jogos');setCustom('');setConfirmed(false)}
   catch(e:any){setError(e.message)}finally{setSaving(false)}
 }
 if(!pending.length) return null
 return <section className="bt-club-conciliation" aria-label="Conciliação de clubes">
   <div className="bt-conciliation-header"><div><h2>Conciliação de nomes de clubes</h2>
    <p><strong>{integer(pending.length)} divergências</strong> entre histórico de jogos e odds exigem revisão. Escolha uma grafia padrão para usar em todas as abas. A decisão ficará salva para futuras cargas.</p></div>
    <span className="bt-pending-flag">Revisão necessária</span></div>
   <div className="bt-club-list">{pending.slice(0,visible).map(item=>{
    const key=keyOf(item)
    return <div className="bt-club-item" key={key}>
      <div className="bt-club-labels"><div><small>historico_jogos</small><strong>{item.historico_jogos}</strong></div>
       <span className="bt-club-arrow">↔</span><div><small>historico_odds</small><strong>{item.historico_odds}</strong></div>
       <small>{item.posicao==='casa'?'Mandante':'Visitante'} · {integer(item.ocorrencias)} jogo(s)</small>
       <button className="bt-secondary" onClick={()=>toggle(item)}>{expanded===key?'Fechar':'Conciliar'}</button>
      </div>
      {expanded===key&&<div className="bt-club-editor">
       <p>Conferência: {item.exemplo_data.split('-').reverse().join('/')} · Jogos: <strong>{item.exemplo_jogo}</strong> · Odds: <strong>{item.exemplo_odds}</strong></p>
       {item.confianca==='verificar'&&<p className="bt-club-warning">A correspondência foi sugerida apenas por data e temporada. Confira com atenção se representam a mesma partida.</p>}
       <div className="bt-club-radio"><label><input type="radio" checked={choice==='jogos'} onChange={()=>setChoice('jogos')}/> {item.historico_jogos}</label>
       <label><input type="radio" checked={choice==='odds'} onChange={()=>setChoice('odds')}/> {item.historico_odds}</label>
       <label><input type="radio" checked={choice==='custom'} onChange={()=>setChoice('custom')}/> Outro nome</label></div>
       {choice==='custom'&&<input className="bt-club-custom" value={custom} onChange={e=>setCustom(e.target.value)} maxLength={180} placeholder="Nome padrão que aparecerá no site"/>}
       {item.confianca==='verificar'&&<label className="bt-club-check"><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/> Confirmei que os nomes representam o mesmo clube</label>}
       <p>Nome padrão selecionado: <strong>{standard||'—'}</strong></p>
       {error&&<p className="bt-error" role="alert">{error}</p>}
       <button className="bt-primary" disabled={saving||!standard.trim()||(item.confianca==='verificar'&&!confirmed)} onClick={submit}>{saving?'Salvando...':'Salvar conciliação'}</button>
      </div>}
    </div>
   })}</div>
   {visible<pending.length&&<button className="bt-secondary bt-more-clubs" onClick={()=>setVisible(v=>v+20)}>Mostrar mais divergências</button>}
   <p className="bt-note">Nenhum clube é conciliado por similaridade sem uma decisão anterior. As tabelas originais não são modificadas. Confrontos sem identificação segura ficam fora do cruzamento das odds.</p>
 </section>
}

function UnresolvedFixtures({items,onSave}:{items:UnresolvedFixture[];onSave:(game:UnresolvedFixture,odd:OddFixtureCandidate,side:'casa'|'fora',standard:string)=>Promise<void>}) {
 const [active,setActive]=useState<number|null>(null)
 const [candidate,setCandidate]=useState(0)
 const [side,setSide]=useState<'casa'|'fora'>('casa')
 const [choice,setChoice]=useState('jogos')
 const [custom,setCustom]=useState('')
 const [confirmed,setConfirmed]=useState(false)
 const [saving,setSaving]=useState(false)
 const [error,setError]=useState('')
 const [visible,setVisible]=useState(20)
 const game=active===null?null:items[active]
 const odd=game?.candidatos[candidate]
 const fromGame=game?(side==='casa'?game.jogos_casa:game.jogos_fora):''
 const fromOdds=odd?(side==='casa'?odd.odds_casa:odd.odds_fora):''
 const standard=choice==='jogos'?fromGame:choice==='odds'?fromOdds:custom.trim()
 const open=(index:number)=>{setActive(old=>old===index?null:index);setCandidate(0);setSide('casa');setChoice('jogos');setConfirmed(false);setError('');setCustom('')}
 const save=async()=>{
   if(!game||!odd||!confirmed||!standard.trim()){setError('Confira o confronto e escolha o nome padrão.');return}
   if(fromGame.trim()===fromOdds.trim()){setError('Nesta posição não há divergência; selecione o outro clube.');return}
   setSaving(true);setError('')
   try{await onSave(game,odd,side,standard.trim());setActive(null);setConfirmed(false)}
   catch(e:any){setError(e.message)}finally{setSaving(false)}
 }
 if(!items.length)return null
 return <section className="bt-club-conciliation bt-fixture-conciliation" aria-label="Confrontos sem identificação segura">
   <div className="bt-conciliation-header"><div><h2>Confrontos que precisam de identificação manual</h2>
    <p>Em <strong>{integer(items.length)} partidas</strong>, há mais de uma cotação possível na mesma data ou os nomes são totalmente diferentes. Escolha primeiro qual confronto corresponde ao registro original.</p></div>
    <span className="bt-pending-flag">Não conciliados</span></div>
   {items.slice(0,visible).map((item,index)=><div className="bt-club-item" key={`${item.data}-${item.temporada}-${item.jogos_casa}-${item.jogos_fora}-${index}`}>
     <div className="bt-club-labels"><div><small>{item.data.split('-').reverse().join('/')} · {item.temporada}</small><strong>{item.jogos_casa} × {item.jogos_fora}</strong></div>
       <span>{item.candidatos.length} confronto(s) possíveis</span><button className="bt-secondary" onClick={()=>open(index)}>{active===index?'Fechar':'Identificar partida'}</button></div>
     {active===index&&<div className="bt-club-editor">
       <p>Selecione o jogo equivalente na tabela <code>historico_odds</code>:</p>
       <select className="bt-fixture-select" value={candidate} onChange={e=>{setCandidate(Number(e.target.value));setConfirmed(false)}}>
        {item.candidatos.map((c,i)=><option key={`${c.odds_casa}-${c.odds_fora}-${i}`} value={i}>{c.odds_casa} × {c.odds_fora}</option>)}
       </select>
       <div className="bt-club-radio"><label><input type="radio" checked={side==='casa'} onChange={()=>{setSide('casa');setChoice('jogos')}}/> Conciliar mandante</label>
        <label><input type="radio" checked={side==='fora'} onChange={()=>{setSide('fora');setChoice('jogos')}}/> Conciliar visitante</label></div>
       <p>Como o clube será apresentado no site?</p>
       <div className="bt-club-radio"><label><input type="radio" checked={choice==='jogos'} onChange={()=>setChoice('jogos')}/> {fromGame}</label>
        <label><input type="radio" checked={choice==='odds'} onChange={()=>setChoice('odds')}/> {fromOdds}</label>
        <label><input type="radio" checked={choice==='custom'} onChange={()=>setChoice('custom')}/> Outro nome</label></div>
       {choice==='custom'&&<input className="bt-club-custom" maxLength={180} value={custom} onChange={e=>setCustom(e.target.value)} placeholder="Nome padrão para o clube"/>}
       <label className="bt-club-check"><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/> Conferi que os dois registros são da mesma partida e que esses nomes representam o mesmo clube</label>
       {error&&<p className="bt-error" role="alert">{error}</p>}
       <button className="bt-primary" disabled={saving||!confirmed||!standard.trim()||fromGame.trim()===fromOdds.trim()} onClick={save}>{saving?'Salvando...':'Salvar esta conciliação'}</button>
       <p className="bt-note">Se os dois clubes tiverem nomes diferentes, concilie um de cada vez. Após salvar, o segundo aparecerá na lista de divergências simples, quando a correspondência ficar identificável.</p>
     </div>}
   </div>)}
   {visible<items.length&&<button className="bt-secondary bt-more-clubs" onClick={()=>setVisible(v=>v+20)}>Mostrar mais confrontos</button>}
 </section>
}

function StrategyPanel({data,bounds,onApply,loading}:{data:StrategyData;bounds:Bounds;onApply:(market:StrategyMarket,range:StrategyRange)=>void;loading:boolean}){
 const [key,setKey] = useState(data.default_market||data.markets[0]?.key||'')
 useEffect(()=>{if(!data.markets.some(m=>m.key===key))setKey(data.default_market||data.markets[0]?.key||'')},[data,key])
 const market = data.markets.find(m=>m.key===key)
 const candidates = market?.suggestions||[]
 const observed = market?.kind==='observed_profit'
 const isActive = (r:StrategyRange)=>!!market &&
    Number((bounds[market.filter_key+'_min']||'').replace(',','.'))===r.odd_min &&
    Number((bounds[market.filter_key+'_max']||'').replace(',','.'))===r.odd_max
 return <section className="bt-annual-panel bt-strategy-panel" aria-label="Sugestão de faixas de odds">
  <div className="bt-annual-title bt-strategy-head"><div>
   <span className="bt-eyebrow">ANÁLISE DE ESTRATÉGIAS</span>
   <h3>Faixas de odds para testar estratégias</h3>
   <span>Intervalos históricos que respeitam todos os filtros atuais · amostra cronológica 70% inicial / 30% posterior</span>
  </div>
  {data.markets.length===1?<span className="bt-tag">{market?.label}</span>:<select aria-label="Mercado para sugerir odds" value={key} onChange={e=>setKey(e.target.value)}>{data.markets.map(m=><option key={m.key} value={m.key}>{m.label}</option>)}</select>}
  </div>
  {market&&<>
   <div className="bt-strategy-summary">
    <strong>{market.reference_label}</strong>
    <span>{integer(market.reference_games)} jogos com odds de referência · {integer(market.quoted_games)} com odd real para liquidar {market.label}</span>
    <span className={observed?'bt-strategy-mode-priced':'bt-strategy-mode-frequency'}>{observed?'Candidatas com ROI positivo nos dois períodos':'Apenas frequência histórica · sem comprovação de lucro'}</span>
   </div>
   {candidates.length>0?<div className="bt-table"><table><thead><tr>
    <th>Faixa de odds <small>referência</small></th><th>Jogos <small>Total</small></th><th>Green / Red</th><th>Win Rate</th>
    {observed?<><th>ROI inicial <small>70%</small></th><th>ROI posterior <small>30%</small></th><th>ROI total</th><th>Lucro total <small>R$ 100 por entrada</small></th></>:<><th>Win Rate posterior <small>30%</small></th><th>Odd Lay de equilíbrio <small>Sem margem; não é cotação</small></th></>}
    <th>Estratégia</th></tr></thead><tbody>
    {candidates.map((r,i)=><tr key={`${market.key}-${i}-${r.odd_min}-${r.odd_max}`}>
     <td><strong>{n(r.odd_min,2)} a {n(r.odd_max,2)}</strong></td>
     <td>{integer(r.total.games)} <small className="bt-strategy-count">({r.training.games} + {r.validation.games})</small></td>
     <td>{integer(r.total.wins)} / {integer(r.total.losses)}</td>
     <td>{n(r.total.win_rate)}%</td>
     {observed?<>
      <td className={r.training.roi!=null&&r.training.roi>0?'positive':'negative'}>{n(r.training.roi)}%</td>
      <td className={r.validation.roi!=null&&r.validation.roi>0?'positive':'negative'}>{n(r.validation.roi)}%</td>
      <td className={r.total.roi!=null&&r.total.roi>0?'positive':'negative'}><strong>{n(r.total.roi)}%</strong></td>
      <td className={r.total.profit!=null&&r.total.profit>0?'positive':'negative'}><strong>{money(r.total.profit)}</strong></td>
     </>:<><td>{n(r.validation.win_rate)}%</td><td>{r.total.fair_lay_odd==null?'Indeterminada':n(r.total.fair_lay_odd,2)}</td></>}
     <td><button className="bt-secondary bt-strategy-apply" type="button" disabled={loading||isActive(r)} onClick={()=>onApply(market,r)}>{isActive(r)?'Em uso':'Aplicar faixa'}</button></td>
    </tr>)}
   </tbody></table></div>:<div className="bt-strategy-empty">
    {observed?'Nenhuma faixa passou pelos critérios de amostra mínima e ROI positivo nos períodos inicial e posterior. Não há estratégia rentável demonstrada neste recorte.':
     market.reference_games===0?'Não existem odds de referência conciliadas para este mercado com os filtros informados.':'Sem amostra suficiente para indicar uma faixa. Quando não há cotação real de Lay, o sistema não calcula lucro nem ROI.'}
   </div>}
   <p className="bt-note">{observed?'Critério: mínimo de 20 apostas precificadas (14 iniciais + 6 posteriores), ambas as partes com ROI positivo, sem comissão. O cálculo usa a odd REAL do mercado, nunca uma cotação simulada.':'As faixas selecionam partidas por odds Back de referência quando o mercado é Lay. A odd Lay de equilíbrio vem da taxa histórica de acerto; não representa cotação disponível nem lucro esperado.'} Faixas predefinidas e comparação cronológica são exploração histórica, sujeita a seleção de resultados e variação futura. O botão aplica a faixa aos filtros e atualiza a conferência de jogos.</p>
  </>}
 </section>
}

function HistoricalTrendsPanel({data}:{data:TrendData}){
 return <section className="bt-annual-panel bt-strategy-panel" aria-label="Consistência do Win Rate">
  <div className="bt-annual-title bt-strategy-head"><div>
   <span className="bt-eyebrow">ANÁLISE DE ESTRATÉGIAS · SEM ODDS</span>
   <h3>Win Rate por mercado — comparação histórica</h3>
   <span>Mesmos mercados e filtros · 70% das partidas mais antigas / 30% das mais recentes</span>
  </div><span className="bt-tag">historico_jogos</span></div>
  <div className="bt-table"><table><thead><tr><th>Mercado</th><th>Jogos</th><th>Green / Red</th><th>WR inicial <small>70%</small></th><th>WR posterior <small>30%</small></th><th>WR total</th></tr></thead><tbody>
   {data.markets.map(row=><tr key={row.key}><td><strong>{row.label}</strong></td><td>{integer(row.total.games)}</td><td>{integer(row.total.wins)} / {integer(row.total.losses)}</td><td>{row.initial.win_rate==null?'—':`${n(row.initial.win_rate)}%`}</td><td>{row.posterior.win_rate==null?'—':`${n(row.posterior.win_rate)}%`}</td><td><strong>{row.total.win_rate==null?'—':`${n(row.total.win_rate)}%`}</strong></td></tr>)}
   {!data.markets.length&&<tr><td colSpan={6}>Sem partidas disponíveis neste recorte.</td></tr>}
  </tbody></table></div>
  <p className="bt-note">{data.explanation} Sem cotação não é possível selecionar faixas de odds nem concluir que um mercado é lucrativo. A comparação inicial/posterior ajuda a avaliar estabilidade da frequência de acertos.</p>
 </section>
}

function OddsAudit({data,useOdds}:{data:{markets:{key:string;label:string}[];default_market:string|null;games:Record<string,AuditGame[]>};useOdds:boolean}){
 const [market,setMarket]=useState(data.default_market||data.markets[0]?.key||'')
 useEffect(()=>{
   if (!data.markets.some(m=>m.key===market)) setMarket(data.default_market||data.markets[0]?.key||'')
 },[data,market])
 const rows=data.games[market]||[]
 const selected=data.markets.find(m=>m.key===market)
 const locked=data.markets.length===1
 return <section className="bt-annual-panel bt-audit-panel">
   <div className="bt-annual-title"><div><h3>Conferência de {useOdds?'Greens e Reds':'Acertos e Erros'} — {selected?.label||'Mercado'}</h3>
   <span>Até 40 jogos do mercado desta aba, respeitando temporada, clube e adversário. {useOdds?'Somente odds reais conciliadas são liquidadas.':'Sem odds: todos os jogos e win rate acumulado cronológico.'}</span></div>
   {locked?<span className="bt-tag">{selected?.label}</span>:<select aria-label="Mercado para conferir apostas" value={market} onChange={e=>setMarket(e.target.value)}>{data.markets.map(m=><option key={m.key} value={m.key}>{m.label}</option>)}</select>}
   </div>
   <div className="bt-table"><table><thead><tr><th>Data</th><th>Temporada</th><th>Divisão</th><th>Formato</th><th>Jogo</th><th>Placar</th>{useOdds&&<th>Odd Lay/Back</th>}<th>Resultado</th><th>{useOdds?'L/P (R$ 100)':'Win Rate acumulado'}</th></tr></thead><tbody>
   {rows.map((g,i)=><tr key={`${market}-${g.date}-${g.home}-${g.away}-${i}`}><td>{g.date.split('-').reverse().join('/')}</td><td>{g.season}</td><td>{g.divisao||'—'}</td><td>{g.formato||'—'}</td><td>{g.home} × {g.away}</td><td>{g.score}</td>
    {useOdds&&<td>{g.odd==null?'—':n(g.odd,2)}</td>}<td className={g.green?'positive':'negative'}>{useOdds&&g.priced?(g.green?'Green':'Red'):(g.green?'Acerto':'Erro')}</td><td className={useOdds?(g.green?'positive':'negative'):''}>{useOdds?money(g.profit):`${n(g.cumulative_rate)}% (${integer(g.cumulative_games)} jogos)`}</td></tr>)}
   {!rows.length&&<tr><td colSpan={useOdds?9:8}>Não há partidas disponíveis com os filtros deste mercado.</td></tr>}
   </tbody></table></div>
   <p className="bt-note">{useOdds?'Para Lay, o resultado indica quando a seleção apostada contra não venceu. Sem odd Lay real, é apenas acerto/erro histórico, sem L/P. Quando cotado, Lay usa responsabilidade R$ 100,00 sem comissão.':'Win Rate acumulado = acertos / jogos elegíveis desde o início do período filtrado até esta partida (ordem cronológica). Sem rentabilidade simulada.'}</p>
 </section>
}

export default function Backtesting(){
 const [tab,setTab]=useState<string>('league')
 const [leagueSubtab,setLeagueSubtab]=useState<string>('general')
 const [useOdds,setUseOdds]=useState(false)
 const [countries,setCountries]=useState<Item[]>([])
 const [country,setCountry]=useState<Item|null>(null)
 const [allCompetitions,setAllCompetitions]=useState<Item[]>([])
 const [countriesLoading,setCountriesLoading]=useState(true)
 const [competitionsLoading,setCompetitionsLoading]=useState(true)
 const [optionsLoading,setOptionsLoading]=useState(false)
 const [optionsReadyId,setOptionsReadyId]=useState<number|null>(null)
 const [competition,setCompetition]=useState<Item|null>(null)
 const [leagueContinents,setLeagueContinents]=useState<Item[]>([])
 const [leagueContinent,setLeagueContinent]=useState<Item|null>(null)
 const [leagueCountries,setLeagueCountries]=useState<Item[]>([])
 const [leagueAllCompetitions,setLeagueAllCompetitions]=useState<Item[]>([])
 const [leagueCountry,setLeagueCountry]=useState<Item|null>(null)
 const [leagueCompetition,setLeagueCompetition]=useState<Item|null>(null)
 const [leagueCatalogLoading,setLeagueCatalogLoading]=useState(true)
 const [availableClubs,setAvailableClubs]=useState<Item[]>([])
 const [availableSeasons,setAvailableSeasons]=useState<string[]>([])
 const [availableDivisions,setAvailableDivisions]=useState<string[]>([])
 const [availableFormats,setAvailableFormats]=useState<string[]>([])
 const [divisionFormats,setDivisionFormats]=useState<{divisao:string;formato:string}[]>([])
 const [divisao,setDivisao]=useState('')
 const [formato,setFormato]=useState('')
 const [club,setClub]=useState<Item|null>(null)
 const [opponent,setOpponent]=useState<Item|null>(null)
 const [startSeason,setStartSeason]=useState('all')
 const [leagueYearFrom,setLeagueYearFrom]=useState('')
 const [leagueYearTo,setLeagueYearTo]=useState('')
 const [years,setYears]=useState(3)
 const [bounds,setBounds]=useState<Bounds>(initialBounds)
 const [appliedBounds,setAppliedBounds]=useState<Bounds>(initialBounds)
 const [data,setData]=useState<Data|null>(null)
 const [goalsData,setGoalsData]=useState<GoalsData|null>(null)
 const [loading,setLoading]=useState(false)
 const requestRef=useRef<AbortController|null>(null)
 const [sourcePending,setSourcePending]=useState(false)
 const [error,setError]=useState('')
 const [refreshId,setRefreshId]=useState(0)
 const [filterOpen,setFilterOpen]=useState(true)
 const [pending,setPending]=useState<ClubPending[]>([])
 const [unresolved,setUnresolved]=useState<UnresolvedFixture[]>([])
 const [conciliationMessage,setConciliationMessage]=useState('')
 // Pré-carrega uma única vez as listas pequenas do catálogo em paralelo.
 // Trocar de país filtra os campeonatos em memória, sem novas requisições.
 useEffect(()=>{
  let current=true
  api<Item[]>('/api/countries?with_games=true').then(rows=>{if(current)setCountries(rows)})
   .catch((e:Error)=>{if(current)setError(`Não foi possível carregar os países: ${e.message}`)})
   .finally(()=>{if(current)setCountriesLoading(false)})
  api<Item[]>('/api/competitions').then(rows=>{if(current)setAllCompetitions(rows)})
   .catch((e:Error)=>{if(current)setError(`Não foi possível carregar os campeonatos: ${e.message}`)})
   .finally(()=>{if(current)setCompetitionsLoading(false)})
  api<{continents:Item[];countries:Item[];competitions:Item[];total:number}>('/api/backtesting/league-catalog')
   .then(d=>{if(current){setLeagueContinents(d.continents||[]);setLeagueCountries(d.countries);setLeagueAllCompetitions(d.competitions)}})
   .catch((e:Error)=>{if(current)setError(`Não foi possível carregar os campeonatos do histórico: ${e.message}`)})
   .finally(()=>{if(current)setLeagueCatalogLoading(false)})
  return ()=>{current=false}
 },[])
 const leagueMode = tab==='league'||tab==='goals'
 const goalsMode = tab==='goals'
 const sharedFilterMode = tab==='league'||tab==='goals'||tab==='club_stats'
 const mainCountries=useMemo(()=>!leagueContinent?countries:countries.filter(c=>
  String(leagueCountries.find(l=>l.nome===c.nome)?.continente||c.continente||'')===leagueContinent.nome),[countries,leagueCountries,leagueContinent?.nome])
 const filteredLeagueCountries=useMemo(()=>!leagueContinent?leagueCountries:leagueCountries.filter(c=>c.continente===leagueContinent.nome),[leagueCountries,leagueContinent?.nome])
 const competitions=useMemo(()=>country
  ? allCompetitions.filter(c=>Number(c.pais_id)===country.id)
  : [],[allCompetitions,country?.id])
 const leagueCompetitions=useMemo(()=>leagueCountry
  ? leagueAllCompetitions.filter(c=>Number(c.pais_id)===leagueCountry.id)
  : leagueAllCompetitions.filter(c=>!leagueContinent||c.continente===leagueContinent.nome),[leagueAllCompetitions,leagueCountry?.id,leagueContinent?.nome])
 useEffect(()=>{
  setCompetition(v=>v && competitions.some(c=>c.id===v.id)?v:null);setClub(null);setOpponent(null);setData(null)
 },[country?.id, competitions])
 useEffect(()=>{setData(null)},[leagueCountry?.id,leagueCompetition?.id])
 useEffect(()=>{
  setPending([]);setUnresolved([]);setConciliationMessage('')
  setAvailableClubs([]);setAvailableSeasons([]);setAvailableDivisions([]);setAvailableFormats([]);setDivisionFormats([])
  setDivisao('');setFormato('');setClub(null);setOpponent(null);setStartSeason('all');setData(null)
 },[competition?.id])
 useEffect(()=>{
  let current=true
  setOptionsReadyId(null)
  if(sharedFilterMode){
   setOptionsLoading(true)
   const params = new URLSearchParams()
   if(leagueContinent?.nome)params.set('league_continent',leagueContinent.nome)
   if(leagueCountry?.nome)params.set('league_country',leagueCountry.nome)
   if(leagueCompetition?.nome)params.set('league_competition',leagueCompetition.nome)
   params.set('use_odds',String(useOdds))
   api<{seasons:string[];divisions:string[];formats:string[];division_formats:{divisao:string;formato:string}[]}>(`/api/backtesting/league-options?${params.toString()}`)
    .then(d=>{
      if(!current)return
      setAvailableClubs([]);setAvailableSeasons(d.seasons||[])
      setAvailableDivisions(d.divisions||[]);setAvailableFormats(d.formats||[])
      setDivisionFormats(d.division_formats||[])
      setStartSeason(v=>v!=='all'&&!d.seasons.includes(v)?'all':v)
      setDivisao(v=>v&&!d.divisions.includes(v)?'':v)
      setFormato(v=>v&&!d.formats.includes(v)?'':v)
      setOptionsReadyId(-1)
    }).catch((e:Error)=>{if(current)setError(`Falha ao carregar os filtros da liga: ${e.message}`)})
    .finally(()=>{if(current)setOptionsLoading(false)})
   return ()=>{current=false}
  }
  if(!competition){setOptionsLoading(false);return ()=>{current=false}}
  setOptionsLoading(true)
  api<{clubs:string[];seasons:string[];divisions:string[];formats:string[];division_formats:{divisao:string;formato:string}[]}>(`/api/backtesting/options?competition_id=${competition.id}&use_odds=${useOdds}`)
   .then(d=>{
    if(!current)return
    const clubs = itemNames(d.clubs)
    setAvailableClubs(clubs);setAvailableSeasons(d.seasons)
    setAvailableDivisions(d.divisions||[]);setAvailableFormats(d.formats||[])
    setDivisionFormats(d.division_formats||[])
    setClub(v=>v&&!clubs.some(c=>c.nome===v.nome)?null:v)
    setStartSeason(v=>v!=='all'&&!d.seasons.includes(v)?'all':v)
    setDivisao(v=>v&&!d.divisions.includes(v)?'':v)
    setFormato(v=>v&&!d.formats.includes(v)?'':v)
    setOptionsReadyId(competition.id)
   }).catch((e:Error)=>{if(current)setError(`Falha ao carregar os filtros do campeonato: ${e.message}`)})
   .finally(()=>{if(current)setOptionsLoading(false)})
  return ()=>{current=false}
 },[competition?.id,country?.id,leagueContinent?.nome,leagueCountry?.nome,leagueCompetition?.nome,useOdds,sharedFilterMode])
 // A conciliação (mais demorada) começa somente depois que os filtros
 // estiverem disponíveis e nunca bloqueia a escolha da temporada.
 useEffect(()=>{
  if(leagueMode || !useOdds || !competition || optionsReadyId!==competition.id)return
  let current=true
  api<ConciliationResponse>(`/api/backtesting/conciliation?competition_id=${competition.id}`)
   .then(d=>{if(current){setPending(d.pending||[]);setUnresolved(d.unresolved||[])}})
   .catch((e:Error)=>{if(current)setError(e.message)})
  return ()=>{current=false}
 },[competition?.id,optionsReadyId,useOdds,leagueMode])
 const saveConciliation=async(item:ClubPending,standard:string)=>{
   if(!competition)return
   const response=await api<ConciliationResponse>('/api/backtesting/conciliation',{
     method:'POST',body:JSON.stringify({competition_id:competition.id,historico_jogos:item.historico_jogos,historico_odds:item.historico_odds,nome_padrao:standard})
   })
   setPending(response.pending||[])
   setUnresolved(response.unresolved||[])
   setConciliationMessage(`Conciliação salva. O nome padrão deste clube será “${standard}”.`)
   const d=await api<{clubs:string[];seasons:string[];divisions:string[];formats:string[];division_formats:{divisao:string;formato:string}[]}>(`/api/backtesting/options?competition_id=${competition.id}&use_odds=${useOdds}`)
   setAvailableClubs(itemNames(d.clubs));setAvailableSeasons(d.seasons)
   setAvailableDivisions(d.divisions||[]);setAvailableFormats(d.formats||[])
   setDivisionFormats(d.division_formats||[])
   setClub(null);setOpponent(null);setData(null);setRefreshId(v=>v+1);setError('')
 }
 const saveManualFixture=async(game:UnresolvedFixture,odd:OddFixtureCandidate,side:'casa'|'fora',standard:string)=>{
   if(!competition)return
   const response=await api<ConciliationResponse>('/api/backtesting/conciliation/fixture',{
     method:'POST',body:JSON.stringify({competition_id:competition.id,data:game.data,temporada:game.temporada,
       jogos_casa:game.jogos_casa,jogos_fora:game.jogos_fora,odds_casa:odd.odds_casa,odds_fora:odd.odds_fora,
       posicao:side,nome_padrao:standard,confirma_mesmo_jogo:true})
   })
   setPending(response.pending||[]);setUnresolved(response.unresolved||[])
   setConciliationMessage(`Conciliação salva com o nome padrão “${standard}”.`)
   const d=await api<{clubs:string[];seasons:string[];divisions:string[];formats:string[];division_formats:{divisao:string;formato:string}[]}>(`/api/backtesting/options?competition_id=${competition.id}&use_odds=${useOdds}`)
   setAvailableClubs(itemNames(d.clubs));setAvailableSeasons(d.seasons)
   setAvailableDivisions(d.divisions||[]);setAvailableFormats(d.formats||[]);setDivisionFormats(d.division_formats||[])
   setClub(null);setOpponent(null);setData(null);setRefreshId(v=>v+1);setError('')
 }
 const formatsForDivision=useMemo(()=>!divisao ? availableFormats : [...new Set(divisionFormats.filter(p=>p.divisao===divisao).map(p=>p.formato).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'pt-BR')),[divisao,availableFormats,divisionFormats])
 useEffect(()=>{if(formato&&!formatsForDivision.includes(formato))setFormato('')},[formato,formatsForDivision])
 const opponentChoices=useMemo(()=>availableClubs.filter(c=>c.id!==club?.id),[availableClubs,club?.id])
 useEffect(()=>{if(opponent&&opponent.id===club?.id)setOpponent(null)},[club?.id,opponent?.id])
 const apply = useCallback(async(nextBounds?:Bounds,oddsOverride?:boolean)=>{
  if(tab==='club_stats')return
  if(!sharedFilterMode && !competition){setError('Selecione país e campeonato.');return}
  if(tab==='team'&&!club){setError('Resultado por Time exige que você selecione um clube.');return}
  if(sharedFilterMode){
   const from=leagueYearFrom.trim()?Number(leagueYearFrom):null
   const to=leagueYearTo.trim()?Number(leagueYearTo):null
   if((from!==null&&(!Number.isInteger(from)||from<1850||from>2100))||(to!==null&&(!Number.isInteger(to)||to<1850||to>2100))){setError('Preencha anos válidos entre 1850 e 2100.');return}
   if(from!==null&&to!==null&&from>to){setError('O ano De não pode ser maior que o ano Até.');return}
  }
  requestRef.current?.abort()
  const controller=new AbortController()
  requestRef.current=controller
  const timeout=window.setTimeout(()=>controller.abort(),45000)
  setLoading(true);setError('');setSourcePending(false)
  try {
   if(goalsMode){
    const params={
     continent:leagueContinent?.nome||null,
     league_continent:leagueContinent?.nome||null,
     country:leagueCountry?.nome||null,
     league_country:leagueCountry?.nome||null,
     competition:leagueCompetition?.nome||null,
     league_competition:leagueCompetition?.nome||null,
     year_from:leagueYearFrom.trim()?Number(leagueYearFrom):null,
     year_to:leagueYearTo.trim()?Number(leagueYearTo):null,
     divisao:divisao||null,
     formato:formato||null,
    }
    const response=await api<GoalsData>('/api/backtesting/goals-statistics',{method:'POST',body:JSON.stringify(params),signal:controller.signal})
    if(requestRef.current===controller){setGoalsData(response);setData(null);setSourcePending(false)}
   }else{
    const params:Record<string,unknown>={competition_id:leagueMode?null:competition?.id||null,country_id:leagueMode?null:country?.id||null,use_history_catalog:leagueMode,league_continent:leagueMode?leagueContinent?.nome||null:null,continent:leagueContinent?.nome||null,league_country:leagueMode?leagueCountry?.nome||null:null,league_competition:leagueMode?leagueCompetition?.nome||null:null,tab:tab==='goals'?'league':tab,club:leagueMode?null:club?.nome||null,opponent:leagueMode?null:opponent?.nome||null,start_season:leagueMode?'all':startSeason,year_from:leagueMode&&leagueYearFrom?Number(leagueYearFrom):null,year_to:leagueMode&&leagueYearTo?Number(leagueYearTo):null,divisao:divisao||null,formato:formato||null,years,use_odds:false,statistics_only:true}
    for(const [k,v] of Object.entries(nextBounds||bounds))params[k]=v.trim()?Number(v.replace(',','.')):null
    const response=await api<Data>('/api/backtesting/evaluate',{method:'POST',body:JSON.stringify(params),signal:controller.signal})
    if(requestRef.current===controller){setData(response);setGoalsData(null);setAppliedBounds({...(nextBounds || bounds)});setSourcePending(false)}
   }
  }catch(e:any){
   if(requestRef.current===controller){
    setError(controller.signal.aborted?'A consulta demorou mais de 45 segundos e foi interrompida na interface. Tente filtrar um país ou campeonato.':e.message)
    setData(null);setGoalsData(null)
   }
  }finally{
   window.clearTimeout(timeout)
   if(requestRef.current===controller){requestRef.current=null;setLoading(false)}
  }
 },[competition?.id,country?.id,leagueContinent?.nome,leagueCountry?.nome,leagueCompetition?.nome,tab,club?.nome,opponent?.nome,startSeason,leagueYearFrom,leagueYearTo,divisao,formato,years,bounds,useOdds,leagueMode,goalsMode,sharedFilterMode])
 useEffect(()=>{setData(null);setGoalsData(null)},[tab])
 const applyStrategy = async(market:StrategyMarket,range:StrategyRange)=>{
   const updated={...bounds,[market.filter_key+'_min']:String(range.odd_min),[market.filter_key+'_max']:String(range.odd_max)}
   setBounds(updated)
   setRefreshId(v=>v+1)
   await apply(updated)
 }
 const focused=({mo_home:'back_home',mo_away:'back_away',lay_home:'lay_home',lay_away:'lay_away',lay_big_home:'lay_big_home',lay_big_away:'lay_big_away'} as Record<string,string>)[tab]||''
 const leagueOnly = tab==='league'
 const filterSummary = sharedFilterMode
  ? (leagueCompetition?`${leagueCompetition.nome} · ${leagueYearFrom||'Início'} a ${leagueYearTo||'Hoje'}`:(leagueCountry?`${leagueCountry.nome} · ${leagueYearFrom||'Início'} a ${leagueYearTo||'Hoje'}`:`Todas as ligas · ${leagueYearFrom||'Início'} a ${leagueYearTo||'Hoje'}`))
  : (competition?`${competition.nome} · ${availableSeasons.length} temporadas no histórico`:'Selecione país e competição para começar')
 return <div className="bt-page">
   <header className="bt-page-header"><div><span className="bt-eyebrow">FOOTBALL INTELLIGENCE · ESTATÍSTICAS</span><h1>Estatísticas</h1><p>Resultados históricos, frequências e Win Rate da tabela historico_jogos.</p></div><div className="bt-commit"><span className="bt-status-dot"/> {useOdds?'Com odds reais · Sem simulações':'Sem odds · Apenas Win Rate'}</div></header>
   <section className="bt-filter-panel"><div className="bt-filter-head"><div><h2>Filtros</h2><p>Filtros padrão para todas as abas. O recorte por ano usa a data da partida.</p></div><div className="bt-filter-head-actions"><button className="bt-text-button" onClick={()=>setFilterOpen(v=>!v)}>{filterOpen?'Ocultar filtros':'Exibir filtros'}</button></div></div>
   {filterOpen&&<div className={`bt-filter-grid ${sharedFilterMode ? 'bt-league-filter-grid' : ''}`}>
    <IdAutocomplete label="Continente" value={leagueContinent} options={leagueContinents} onChange={v=>{
      setLeagueContinent(v);setLeagueCountry(null);setLeagueCompetition(null);
      setCountry(null);setCompetition(null);setClub(null);setOpponent(null);setData(null);setGoalsData(null)
    }} disabled={leagueCatalogLoading} loading={leagueCatalogLoading} placeholder="Todos os continentes"/>
    {sharedFilterMode?<>
     <IdAutocomplete label="País" value={leagueCountry} options={filteredLeagueCountries} onChange={v=>{setLeagueCountry(v);setLeagueCompetition(null);setData(null);setGoalsData(null)}} disabled={leagueCatalogLoading} loading={leagueCatalogLoading} placeholder={leagueCatalogLoading?'Carregando países...':'Todos os países'}/>
     <IdAutocomplete label="Competição" value={leagueCompetition} options={leagueCompetitions} onChange={v=>{setLeagueCompetition(v);if(v&&!leagueCountry){const parent=filteredLeagueCountries.find(x=>x.id===Number(v.pais_id));if(parent)setLeagueCountry(parent)};setData(null);setGoalsData(null)}} disabled={leagueCatalogLoading} loading={leagueCatalogLoading} emptyMessage="Nenhum campeonato com jogos neste país" placeholder={leagueCatalogLoading?'Carregando campeonatos...':'Todos os campeonatos'}/>
     <div className="field"><label>Ano — de</label><input aria-label="Ano inicial (data do jogo)" type="number" min={1850} max={2100} step={1} placeholder="Todos os anos" value={leagueYearFrom} onChange={e=>setLeagueYearFrom(e.target.value)}/></div>
     <div className="field"><label>Ano — até</label><input aria-label="Ano final (data do jogo)" type="number" min={1850} max={2100} step={1} placeholder="Todos os anos" value={leagueYearTo} onChange={e=>setLeagueYearTo(e.target.value)}/></div>
     <div className="field"><label>Divisão</label><select aria-label="Divisão" value={divisao} disabled={!availableDivisions.length&&optionsLoading} onChange={e=>setDivisao(e.target.value)}><option value="">Todas as divisões</option>{availableDivisions.map(v=><option key={v} value={v}>{v}</option>)}</select></div>
     <div className="field"><label>Formato</label><select aria-label="Formato" value={formato} disabled={!formatsForDivision.length&&optionsLoading} onChange={e=>setFormato(e.target.value)}><option value="">Todos os formatos</option>{formatsForDivision.map(v=><option key={v} value={v}>{v}</option>)}</select></div>
    </>:<>
     <IdAutocomplete label="País" required value={country} options={mainCountries} onChange={setCountry} disabled={countriesLoading} loading={countriesLoading} placeholder={countriesLoading?'Carregando países...':'Selecionar país...'}/>
     <IdAutocomplete label="Competição" required value={competition} options={competitions} onChange={setCompetition} disabled={!country||competitionsLoading} loading={competitionsLoading} emptyMessage="Nenhum campeonato cadastrado para este país" placeholder={competitionsLoading?'Carregando campeonatos...':'Selecionar campeonato...'}/>
     <div className="field"><label>Divisão</label><select aria-label="Divisão" value={divisao} disabled={!competition||!availableDivisions.length} onChange={e=>setDivisao(e.target.value)}><option value="">Todas as divisões</option>{availableDivisions.map(v=><option key={v} value={v}>{v}</option>)}</select></div>
     <div className="field"><label>Formato</label><select aria-label="Formato" value={formato} disabled={!competition||!formatsForDivision.length} onChange={e=>setFormato(e.target.value)}><option value="">Todos os formatos</option>{formatsForDivision.map(v=><option key={v} value={v}>{v}</option>)}</select></div>
     <IdAutocomplete label="Clube" required={tab==='team'} value={club} options={availableClubs} disabled={!competition} onChange={setClub} placeholder={tab==='team'?'Clube obrigatório':'Todos os clubes'}/>
     <IdAutocomplete label="Adversário" value={opponent} options={opponentChoices} disabled={!club} onChange={setOpponent} placeholder="Todos os adversários"/>
     <div className="field"><label>Temporada inicial</label><select value={startSeason} onChange={(e: React.ChangeEvent<HTMLSelectElement>)=>setStartSeason(e.target.value)}><option value="all">Todas as temporadas</option>{availableSeasons.map(s=><option key={s} value={s}>{s}</option>)}</select></div>
     <div className="field"><label>Resultado dos últimos anos</label><input aria-label="Número de anos" type="number" min={1} max={30} value={years} onChange={(e: React.ChangeEvent<HTMLInputElement>)=>setYears(Math.min(30,Math.max(1,Number(e.target.value)||1)))}/></div>
    </>}
   </div>}
   {((sharedFilterMode&&optionsLoading)||(!sharedFilterMode&&competition&&optionsLoading))&&<p className="bt-note" role="status">{sharedFilterMode?'Carregando temporadas, divisões e formatos...':'Carregando temporadas e clubes...'}</p>}
   {!sharedFilterMode&&country&&!competitionsLoading&&competitions.length===0&&<p className="bt-note" role="status">Este país ainda não possui campeonatos no catálogo. Confira o cadastro da competição.</p>}
   <div className="bt-filter-actions"><button className="bt-primary" disabled={(!sharedFilterMode&&!competition)||(sharedFilterMode&&leagueCatalogLoading)||optionsLoading||(tab==='team'&&!club)||loading} onClick={()=>{setRefreshId(v=>v+1);if(tab!=='club_stats')apply()}}>{loading?'Analisando...':'Aplicar filtros'}</button><span>{filterSummary}</span></div></section>

   <nav className="bt-tabs" aria-label="Mercados de análise">{tabs.map(t=><button key={t.key} className={tab===t.key?'current':''} onClick={()=>setTab(t.key)}>{t.name}</button>)}</nav>

   {tab==='club_stats'&&<ClubStatisticsPanel useOdds={useOdds} setUseOdds={setUseOdds} continents={leagueContinents} countries={leagueCountries} allCompetitions={leagueAllCompetitions} catalogLoading={leagueCatalogLoading} sharedContinent={leagueContinent} sharedCountry={leagueCountry} sharedCompetition={leagueCompetition} hideFilters applyToken={refreshId}/>}

   {tab!=='club_stats'&&<>
   {leagueOnly&&<nav className="bt-club-market-tabs bt-league-market-tabs" aria-label="Mercados das estatísticas por campeonato">{leagueSubtabs.map(item=><button key={item.key} type="button" className={leagueSubtab===item.key?'current':''} aria-current={leagueSubtab===item.key?'page':undefined} onClick={()=>setLeagueSubtab(item.key)}>{item.name}</button>)}</nav>}
   {conciliationMessage&&<p className="bt-club-success" role="status">{conciliationMessage}</p>}
   {useOdds&&competition&&!sharedFilterMode&&<ClubConciliation pending={pending} onSave={saveConciliation}/>}
   {useOdds&&competition&&!sharedFilterMode&&<UnresolvedFixtures items={unresolved} onSave={saveManualFixture}/>}
   {error&&<p role="alert" className="bt-error">{error}</p>}
   {sourcePending&&!loading&&<p role="status" className="bt-source-pending">Fonte selecionada: <strong>{useOdds?'Com odds':'Sem odds'}</strong>. Clique em <strong>Aplicar filtros</strong> para atualizar a análise.</p>}
   {goalsMode&&!goalsData&&!loading&&!error&&<div className="bt-empty"><strong>Escolha os filtros e clique em Aplicar</strong><p>A aba Gols e Resultado usa a linha do tempo de minutos_gols (mandante × visitante).</p></div>}
   {!goalsMode&&!data&&!loading&&!sourcePending&&<div className="bt-empty"><strong>Escolha os filtros para explorar o histórico</strong><p>Os resultados mostram frequência e Win Rate, sem inventar lucro.</p></div>}
   {goalsMode&&goalsData&&<GoalsResultPanel data={goalsData}/>}
   {data&&!goalsMode&&<>
    <section className="bt-section-title"><div><span className="bt-eyebrow">VISÃO PRINCIPAL</span><h2>{leagueOnly?(leagueCompetition?`${leagueCompetition.nome} · ${data.year_from||'Início'} a ${data.year_to||'Hoje'}`:(leagueCountry?`Comparativo das ligas · ${leagueCountry.nome}`:'Comparativo geral entre ligas')):tabs.find(t=>t.key===tab)?.name}</h2><p>{integer(data.games)} partidas na amostra · {data.use_odds?`stake padrão ${money(data.stake)}`:'resultado em Win Rate (sem odds)'} · Divisão: {data.divisao||'Todas'} · Formato: {data.formato||'Todos'}</p></div></section>
    {data.use_odds&&data.games===0&&<p className="bt-source-empty">Nenhuma partida com odds conciliadas em <code>historico_odds</code> neste recorte. Desative Com odds para consultar todos os resultados do histórico de jogos.</p>}
    {leagueOnly&&leagueSubtab==='general'&&<>
     {data.league_overview&&<LeagueOverviewPanel data={data.league_overview} season={`${data.year_from||'início'} a ${data.year_to||'hoje'}`}/>}
     <Cards markets={data.markets} focus="" useOdds={data.use_odds}/>
    </>}
    {!leagueMode&&<Cards markets={data.markets} focus={focused} useOdds={data.use_odds}/>}
    {!leagueMode&&tab==='scores'&&data.scores&&<ScoreTable rows={data.scores.scores} total={data.scores.total}/>}
    {leagueOnly&&leagueSubtab!=='general'&&leagueSubtab!=='scores'&&data.league_comparison&&
     <LeagueComparisonPanel key={`${refreshId}-${data.use_odds}-${leagueSubtab}`} data={data.league_comparison} marketKey={leagueSubtab} useOdds={data.use_odds} divisao={data.divisao} formato={data.formato} appliedBounds={appliedBounds}/>}
    {leagueOnly&&leagueSubtab==='scores'&&data.scores&&<ScoreTable rows={data.scores.scores} total={data.scores.total}/>}

    {tab!=='scores'&&!leagueMode&&<div className="bt-analytics-grid">
      <AnnualTable key={`${tab}-${refreshId}`} annual={data.annual} markets={data.markets} years={data.years} focus={tab} useOdds={data.use_odds} seasonMode={false} caption={data.use_odds?`Lucro/prejuízo — últimos ${years} anos`:`Win Rate — últimos ${years} anos`}/>

      {data.use_odds?<aside className="bt-odd-filters"><div className="bt-odd-head"><h3>Filtros de odds</h3><p>Aplique intervalos de preços por mercado.</p></div>
       {oddsGroups.map(g=><div className="bt-odd-group" key={g.key}><label>{g.name}</label><div><input inputMode="decimal" placeholder="Odd mín." aria-label={`${g.name} mínima`} value={bounds[g.key+'_min']} onChange={(e: React.ChangeEvent<HTMLInputElement>)=>setBounds(v=>({...v,[g.key+'_min']:e.target.value}))}/><input inputMode="decimal" placeholder="Odd máx." aria-label={`${g.name} máxima`} value={bounds[g.key+'_max']} onChange={(e: React.ChangeEvent<HTMLInputElement>)=>setBounds(v=>({...v,[g.key+'_max']:e.target.value}))}/></div></div>)}
       <button className="bt-secondary" disabled={loading} onClick={()=>apply()}>Aplicar odds</button><button className="bt-quiet" onClick={()=>setBounds(initialBounds)}>Limpar valores</button>
       <p className="bt-note">As odds de 1X2, Over 0,5, Over 1,5, Over 2,5, Under 3,5 e Ambos Marcam são consultadas em historico_odds, quando conciliadas com o placar de historico_jogos. Sem correspondência, o L/P fica indisponível.</p>
      </aside>:<aside className="bt-history-info"><h3>Modo Sem odds</h3><p>Fonte: <strong>historico_jogos</strong></p><p>Todas as partidas concluídas do recorte são analisadas. Cada mercado apresenta Green, Red e Win Rate — sem unidades, ROI ou lucro.</p><p>Para analisar preços e rentabilidade, acesse Scanner.</p></aside>}
    </div>}
    {!leagueMode&&data.odds_suggestions&&data.use_odds&&tab!=='scores'&&<StrategyPanel data={data.odds_suggestions} bounds={bounds} loading={loading} onApply={applyStrategy}/>}
    {!leagueMode&&data.historical_trends&&!data.use_odds&&tab!=='scores'&&<HistoricalTrendsPanel data={data.historical_trends}/>}
    {!leagueMode&&data.odds_audit&&tab!=='scores'&&<OddsAudit data={data.odds_audit} useOdds={data.use_odds}/>}
    {!leagueMode&&data.use_odds&&data.odds_reconciliation&&<section className="bt-reconciliation" aria-label="Conciliação de odds">
       <strong>Conciliação de odds e resultados</strong>
       <span>{integer(data.odds_reconciliation.matched_games)} jogos conciliados com <code>historico_odds</code></span>
       <span>{integer(data.odds_reconciliation.legacy_only_games)} com odds antigas</span>
       <span>{integer(data.odds_reconciliation.without_any_odds)} sem cotação</span>
       {data.odds_reconciliation.ambiguous_games>0&&<span className="bt-error">{integer(data.odds_reconciliation.ambiguous_games)} correspondências ambíguas não liquidadas</span>}
       {data.odds_reconciliation.status==='tabela_ausente'&&<span>historico_odds não encontrada; usando as odds antigas disponíveis.</span>}
       {data.odds_reconciliation.status==='schema_incompleto'&&<span className="bt-error">Tabela historico_odds sem todas as colunas necessárias.</span>}
       <p>Divisão e formato identificados na cotação conciliada. Chave: país + campeonato + temporada + data + mandante + visitante. Placar: historico_jogos. Consulte os resultados dos mercados nos cards e nos gráficos.</p>
    </section>}
    {data.head_to_head&&<section className="bt-h2h"><div className="bt-section-title"><div><span className="bt-eyebrow">HEAD TO HEAD</span><h2>Confronto direto · {data.club} × {data.opponent}</h2><p>{integer(data.head_to_head.games)} jogos em todas as temporadas filtradas</p></div></div>
      <Cards markets={data.head_to_head.markets} focus={focused} useOdds={data.use_odds}/>
      {tab==='scores'?<ScoreTable rows={data.head_to_head.scores.scores} total={data.head_to_head.scores.total}/>:<AnnualTable key={`${tab}-h2h-${refreshId}`} annual={data.head_to_head.annual} markets={data.head_to_head.markets} years={data.years} focus={tab} useOdds={data.use_odds} caption={data.use_odds?"Confronto direto · resultado anual":"Confronto direto · Win Rate anual"}/>}
    </section>}
    {!leagueMode&&<p className="bt-bottom-note">{data.explanation} {data.use_odds?'Para Back, a odd indicada é o mínimo de equilíbrio; para Lay, o máximo.':''} Goleada: vitória com 4 ou mais gols do clube, sem exigência de margem de gols. Taxas históricas não garantem EV positivo futuro.</p>}
   </>}
   </>}
  </div>
}
