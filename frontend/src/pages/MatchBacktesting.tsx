import { useEffect, useState } from 'react'
import { api, query } from '../api'
import {
 ANALYSIS_INTERVALS, ANALYSIS_TABS, AnalysisTab, MatchAnalysis, MatchAnalysisBody, TeamBadge,
} from '../components/MatchAnalysisViews'

export default function MatchBacktesting(){
 const [country,setCountry]=useState('')
 const [competition,setCompetition]=useState('')
 const [home,setHome]=useState('')
 const [away,setAway]=useState('')
 const [intervalGames,setIntervalGames]=useState(30)
 const [countries,setCountries]=useState<string[]>([])
 const [competitions,setCompetitions]=useState<string[]>([])
 const [teams,setTeams]=useState<string[]>([])
 const [loading,setLoading]=useState(false)
 const [optionsLoading,setOptionsLoading]=useState(false)
 const [error,setError]=useState('')
 const [result,setResult]=useState<MatchAnalysis|null>(null)
 const [tab,setTab]=useState<AnalysisTab>('geral')
 const [shields,setShields]=useState<Record<string,string>>({})
 useEffect(()=>{
  let active=true
  setOptionsLoading(true)
  api<{countries:string[];competitions:string[];teams:string[]}>(`/api/analysis-v3/match/options?${query({country,competition})}`)
   .then(r=>{if(active){setCountries(r.countries);setCompetitions(r.competitions);setTeams(r.teams)}})
   .catch((e:Error)=>{if(active)setError(e.message)})
   .finally(()=>{if(active)setOptionsLoading(false)})
  return ()=>{active=false}
 },[country,competition])
 const analyze=async()=>{
  if(!home.trim()||!away.trim()||home.trim().toLocaleLowerCase()===away.trim().toLocaleLowerCase()){setError('Selecione dois clubes diferentes.');return}
  setLoading(true);setError('');setResult(null)
  try{
   const value=await api<MatchAnalysis>('/api/analysis-v3/match/analyze',{method:'POST',body:JSON.stringify({country:country||null,competition:competition||null,home:home.trim(),away:away.trim(),interval_games:intervalGames})})
   setResult(value);setTab('geral');setShields({})
   const params=new URLSearchParams();params.append('names',value.home);params.append('names',value.away)
   if(value.country)params.set('country',value.country)
   api<Record<string,string>>(`/api/analysis-v3/match/shields?${params}`).then(setShields).catch(()=>setShields({}))
  }catch(e:any){setError(e.message)}finally{setLoading(false)}
 }
 return <div className="a3-page">
  <header className="a3-head"><div><small>FOOTBALL INTELLIGENCE · SOFASCORE</small><h1>Backtesting · Inteligência de Confrontos</h1><p>Estatísticas recentes, sequência de gols e projeção probabilística por aprendizado de máquina.</p></div><span className="a3-source">jogos + jogo_completo + minutos_gols</span></header>
  <section className="a3-panel"><h2>Confronto e intervalo dos jogos</h2>
   <div className="a3-filters a3-sofa-filters">
    <label>País<select value={country} onChange={e=>{setCountry(e.target.value);setCompetition('');setHome('');setAway('')}}><option value="">Todos os países</option>{countries.map(c=><option key={c}>{c}</option>)}</select></label>
    <label>Campeonato<select value={competition} onChange={e=>{setCompetition(e.target.value);setHome('');setAway('')}}><option value="">Todos os campeonatos</option>{competitions.map(c=><option key={c}>{c}</option>)}</select></label>
    <label>Mandante<input list="sofa-home-teams" value={home} onChange={e=>setHome(e.target.value)} placeholder="Mandante"/></label>
    <label>Visitante<input list="sofa-away-teams" value={away} onChange={e=>setAway(e.target.value)} placeholder="Visitante"/></label>
    <label>Últimos jogos por clube<select value={intervalGames} onChange={e=>setIntervalGames(Number(e.target.value))}>{ANALYSIS_INTERVALS.map(i=><option key={i} value={i}>{i} jogos</option>)}</select></label>
    <datalist id="sofa-home-teams">{teams.filter(t=>t.trim().toLocaleLowerCase()!==away.trim().toLocaleLowerCase()).map(t=><option key={t} value={t}/>)}</datalist>
    <datalist id="sofa-away-teams">{teams.filter(t=>t.trim().toLocaleLowerCase()!==home.trim().toLocaleLowerCase()).map(t=><option key={t} value={t}/>)}</datalist>
   </div>
   <div className="a3-actions"><button disabled={loading} onClick={analyze}>{loading?'Calculando...':'Analisar confronto'}</button><span>{optionsLoading?'Carregando clubes...':'As estatísticas são calculadas apenas ao clicar em Analisar confronto.'}</span></div>
  </section>
  {error&&<p className="a3-error" role="alert">{error}</p>}
  {result&&<>
   <div className="a3-versus"><TeamBadge name={result.home} shield={shields[result.home]}/><span>×</span><TeamBadge name={result.away} shield={shields[result.away]}/></div>
   <nav className="a3-analysis-tabs" aria-label="Categorias do confronto">{ANALYSIS_TABS.map(item=><button key={item.id} type="button" onClick={()=>setTab(item.id)} className={tab===item.id?'selected':''} aria-current={tab===item.id?'page':undefined}>{item.label}</button>)}</nav>
   <MatchAnalysisBody data={result} tab={tab} onError={setError}/>
  </>}
 </div>
}
