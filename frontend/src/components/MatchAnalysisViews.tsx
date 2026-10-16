import { useEffect, useState } from 'react'
import RadarChart from './RadarChart'

export type Metric = {key:string;label:string;home:number|null;away:number|null;percent:boolean}
export type Probability = {key:string;label:string;group:string;kind:'back'|'lay';probability:number|null;fair_odd:number|null}
type GoalRate = {value:number|null;count:number;total:number}
type GoalMetrics = {valid_games:number;requested_games:number;goals_recorded:number;
 opened:GoalRate;extended_after_open:GoalRate;equalized_after_open:GoalRate;
 won_after_open:GoalRate;lost_after_open:GoalRate;first_half:GoalRate;second_half:GoalRate;
 minute_bands:{label:string;value:number|null;count:number;total:number}[]}
type CsState = 'winning'|'drawing'|'losing'
type CsTeam = {requested_games:number;valid_games:number;total_minutes:number;
 final_scores:{score:string;state:CsState;count:number;pct:number|null}[];
 time_by_state:Record<CsState,{minutes:number;pct:number|null}>;
 scores:{score:string;state:CsState;minutes:number;pct:number|null;games:number;avg_minutes:number|null}[]}
type GoalReport = {home:GoalMetrics|null;away:GoalMetrics|null;warning:string|null;denominators?:string;
 correct_score?:{home:CsTeam;away:CsTeam}}
type Score = {score:string;probability:number}
type Strength = {attack:number|null;defense:number|null;creativity:number|null;strength:number|null}
type Projection = {most_likely:Score;least_likely:Score;score_scope:string;zebra_one_zero:Score&{team:string};
 simulations:Record<string,number>;simulation_count:number;
 ml:{status:string;reason?:string|null;training_games:number;validation_games:number;baseline_log_loss?:number;model_log_loss?:number};
 radar:{home:Strength;away:Strength}}
type ResultsSnapshot = {games:number;wins:number;draws:number;losses:number;goals_for:number;goals_against:number;clean_sheets:number;scored_games:number}
export type MatchAnalysis = {
 home:string;away:string;country:string|null;competition:string|null;interval_games:number;
 comparison:Metric[];probabilities:Probability[];goals:GoalReport;projection:Projection;
 recent_results?:{home:ResultsSnapshot;away:ResultsSnapshot};
 expected_goals:{home:number;away:number};
 method:{name:string;data_source:string;home_games:number;away_games:number;home_venue_games:number;away_venue_games:number;
 h2h_games:number;h2h_model_games:number;xg_home_games:number;xg_away_games:number;quality:string;half_life_days:number;underdog:string;lay_zebra_score:string;warnings:string[]}
}
export type AnalysisTab = 'geral'|'gols'|'correct_score'|'ataque'|'defesa'|'projecao'
export const ANALYSIS_TABS:{id:AnalysisTab;label:string}[]=[
 {id:'geral',label:'Geral'},{id:'gols',label:'Gols'},{id:'correct_score',label:'Correct Score'},{id:'ataque',label:'Ataque'},
 {id:'defesa',label:'Defesa'},{id:'projecao',label:'Projeção'}]
export const ANALYSIS_INTERVALS=[5,10,20,30,50,100]

const n=(v:number|null|undefined,places=1)=>v==null?'—':v.toLocaleString('pt-BR',{minimumFractionDigits:places,maximumFractionDigits:places})
const pct=(v:number|null|undefined)=>v==null?'—':`${n(v)}%`
const MARKET_GROUPS:[string,string][] = [
 ['mo_ft','Match Odds FT'],['over_ft','Over FT'],['under_ft','Under FT'],
 ['btts','Ambos Marcam'],['double_chance','Dupla Chance'],['correct_score','Placar Exato'],
 ['big','Goleadas'],['lay','Lay'],['mo_ht','Match Odds HT (sem dados)'],
 ['over_ht','Over HT (sem dados)'],['under_ht','Under HT (sem dados)']]
const HIGHLIGHTS=['home_win','draw','away_win','over_1_5_ft','over_2_5_ft','btts','big_home','big_away']
const ATTACK_KEYS=new Set(['xg','gols_esperados_no_alvo','chutes_gol','total_chutes','chutes_dentro_area',
 'grandes_chances_criadas','grandes_chances_perdidas','escanteios','goals_for','posse_bola','passes_certos',
 'pct_chutes_alvo','chutes_por_gol','chutes_alvo_por_gol','conversao_chutes','conversao_alvo','pct_chutes_area',
 'xg_por_chute','conversao_grandes','gols_menos_xg'])
const GENERAL_KEYS=new Set(['goals_for','goals_against','xg','xg_against','posse_bola','chutes_gol','total_chutes',
 'grandes_chances_criadas','percentual_duelos_vencidos','pct_chutes_alvo','chutes_por_gol','chutes_alvo_por_gol'])
const DEFENCE_KEYS=new Set(['xg_against','chutes_bloqueados','total_desarmes','interceptacoes','recuperacoes_bola',
 'defesas_goleiro','shots_against','sot_against','percentual_duelos_vencidos','goals_against',
 'chutes_sofridos_por_gol','chutes_alvo_sofridos_por_gol','pct_defesas','xg_por_chute_sofrido','gols_sofridos_menos_xg'])
const GOAL_RATES:{key:keyof GoalMetrics;label:string;note:string}[]=[
 {key:'opened',label:'Jogos em que abriu o placar',note:'% dos jogos com linha do tempo completa'},
 {key:'extended_after_open',label:'Ampliou a vantagem após abrir',note:'% dos jogos em que abriu o placar'},
 {key:'equalized_after_open',label:'Sofreu empate após abrir',note:'% dos jogos em que abriu o placar'},
 {key:'won_after_open',label:'Venceu após abrir o placar',note:'% dos jogos em que abriu o placar'},
 {key:'lost_after_open',label:'Perdeu após abrir o placar',note:'% dos jogos em que abriu o placar'},
 {key:'first_half',label:'Gols no primeiro tempo',note:'% dos gols registrados do clube'},
 {key:'second_half',label:'Gols no segundo tempo',note:'% dos gols registrados do clube'},
]

export function TeamBadge({name,shield}:{name:string;shield?:string}) {
 const [failed,setFailed]=useState(false)
 useEffect(()=>setFailed(false),[shield])
 const initials=name.split(/\s+/).filter(Boolean).slice(0,2).map(w=>w[0]).join('').toUpperCase()
 return <div className="a3-team-badge">
  {shield&&!failed?<img src={shield} alt={`Escudo ${name}`} referrerPolicy="no-referrer" onError={()=>setFailed(true)}/>:<span className="a3-badge-fallback" aria-hidden="true">{initials}</span>}
  <strong>{name}</strong></div>
}

function Comparison({data,items,title}:{data:MatchAnalysis;items:Metric[];title:string}) {
 return <section className="a3-panel a3-match-table"><h2>{title}</h2>
  {items.length===0?<p className="a3-note">Não há estatísticas suficientes neste grupo.</p>:<>
   <div className="a3-side-head"><strong>{data.home}</strong><span>INDICADOR</span><strong>{data.away}</strong></div>
   {items.map(item=>{
    const left=item.home??0,right=item.away??0,max=Math.max(left,right,1)
    return <div className="a3-duel-row" key={item.key}>
     <div className="a3-duel-side"><span>{item.home==null?'—':`${n(item.home,2)}${item.percent?'%':''}`}</span><div className="a3-duel-track"><i style={{width:`${Math.max(0,left/max*100)}%`}}/></div></div>
     <strong>{item.label}</strong>
     <div className="a3-duel-side right"><div className="a3-duel-track"><i style={{width:`${Math.max(0,right/max*100)}%`}}/></div><span>{item.away==null?'—':`${n(item.away,2)}${item.percent?'%':''}`}</span></div>
    </div>})}</>}
 </section>
}

function Scoreboard({data}:{data:MatchAnalysis}) {
 const h=data.recent_results?.home,a=data.recent_results?.away
 if(!h||!a)return null
 const items:{label:string;key:keyof ResultsSnapshot}[]=[
  {label:'Jogos',key:'games'},{label:'Vitórias',key:'wins'},{label:'Empates',key:'draws'},
  {label:'Derrotas',key:'losses'},{label:'Gols marcados',key:'goals_for'},
  {label:'Gols sofridos',key:'goals_against'},{label:'Clean sheets',key:'clean_sheets'},
  {label:'Jogos em que marcou',key:'scored_games'}]
 return <section className="a3-panel"><h2>Resultados recentes · últimos {data.interval_games} jogos</h2>
  <div className="a3-score-grid">{items.map(item=><article key={item.key}><small>{item.label}</small>
   <div><strong>{n(h[item.key],0)}</strong><span>×</span><strong>{n(a[item.key],0)}</strong></div>
  </article>)}</div>
  <p className="a3-note">Mandante à esquerda; visitante à direita. As contagens referem-se à seleção de jogos de cada clube, não a jogos futuros.</p>
 </section>
}

function GoalCard({data}:{data:MatchAnalysis}) {
 const left=data.goals?.home,right=data.goals?.away
 return <section className="a3-panel"><h2>Gols · comportamento após abertura do placar</h2>
  {data.goals?.warning&&<p className="a3-warning">{data.goals.warning}</p>}
  {!left||!right?<p className="a3-note">Linha do tempo indisponível. Confirme os campos de `minutos_gols` e a relação com `jogos`.</p>:<>
   <div className="a3-goal-coverage"><span>{data.home}: {left.valid_games} / {left.requested_games} jogos validados</span>
    <span>{data.away}: {right.valid_games} / {right.requested_games} jogos validados</span></div>
   <div className="a3-goal-rows">
    {GOAL_RATES.map(item=>{
     const h=left[item.key] as GoalRate,a=right[item.key] as GoalRate
     return <div key={item.key} className="a3-goal-row">
       <div><strong>{item.label}</strong><small>{item.note}</small></div>
       <div className="a3-goal-pair"><span>{pct(h.value)} <small>({h.count}/{h.total})</small></span>
       <span>{pct(a.value)} <small>({a.count}/{a.total})</small></span></div>
      </div>})}
   </div>
   <h3 className="a3-subtitle">Distribuição dos gols por minuto</h3>
   <p className="a3-note">Cada faixa representa a porcentagem dos gols do clube registrados na linha do tempo validada.</p>
   <div className="a3-minute-head"><strong>{data.home}</strong><span>MINUTOS</span><strong>{data.away}</strong></div>
   {left.minute_bands.map((band,i)=>{
    const other=right.minute_bands[i]
    return <div className="a3-minute-row" key={band.label}>
      <div className="a3-minute-half"><span>{pct(band.value)}</span><div className="a3-minute-track left"><i style={{width:`${band.value??0}%`}}/></div></div>
      <strong>{band.label}</strong>
      <div className="a3-minute-half"><div className="a3-minute-track"><i style={{width:`${other?.value??0}%`}}/></div><span>{pct(other?.value)}</span></div>
     </div>})}
   <p className="a3-note">Gols nos períodos 45+ e 90+ aparecem em faixas próprias. Partidas com eventos incompletos não entram nos percentuais.</p>
  </>}
 </section>
}

const CS_STATES:{key:CsState;label:string}[]=[{key:'winning',label:'Vencendo'},{key:'drawing',label:'Empatando'},{key:'losing',label:'Perdendo'}]
const fmtMin=(v:number|null|undefined)=>v==null?'—':`${n(v,1)} min`

function CorrectScoreTeam({name,team}:{name:string;team:CsTeam}) {
 const maxMin=Math.max(1,...team.scores.map(s=>s.minutes))
 const maxCount=Math.max(1,...team.final_scores.map(s=>s.count))
 return <section className="a3-panel a3-cs-team"><h2>{name}</h2>
  <p className="a3-note">{team.valid_games} / {team.requested_games} jogos com linha do tempo validada · {n(team.total_minutes,0)} minutos analisados.</p>
  <h3 className="a3-subtitle">Tempo vencendo, empatando e perdendo</h3>
  <div className="a3-cs-stack" role="img" aria-label={CS_STATES.map(s=>`${s.label} ${pct(team.time_by_state[s.key].pct)}`).join(', ')}>
   {CS_STATES.map(s=>{const v=team.time_by_state[s.key].pct??0;return v>0?<i key={s.key} className={`cs-${s.key}`} style={{width:`${v}%`}}>{v>=8?pct(v):''}</i>:null})}
  </div>
  <div className="a3-cs-legend">{CS_STATES.map(s=><span key={s.key}><b className={`cs-${s.key}`}/>{s.label}: {pct(team.time_by_state[s.key].pct)} <small>({fmtMin(team.time_by_state[s.key].minutes)})</small></span>)}</div>
  <h3 className="a3-subtitle">Minutos em cada placar</h3>
  <p className="a3-note">Placar sempre na ótica do clube (gols do clube - gols do adversário).</p>
  {team.scores.length===0?<p className="a3-note">Sem dados.</p>:team.scores.map(s=><div className="a3-cs-row" key={s.score}>
   <strong>{s.score}</strong>
   <div className="a3-cs-track"><i className={`cs-${s.state}`} style={{width:`${s.minutes/maxMin*100}%`}}/></div>
   <span>{pct(s.pct)} <small>{fmtMin(s.minutes)} · {s.games} jogos · {fmtMin(s.avg_minutes)}/jogo</small></span>
  </div>)}
  <h3 className="a3-subtitle">Repetição do placar final</h3>
  {team.final_scores.length===0?<p className="a3-note">Sem dados.</p>:team.final_scores.map(s=><div className="a3-cs-row" key={s.score}>
   <strong>{s.score}</strong>
   <div className="a3-cs-track"><i className={`cs-${s.state}`} style={{width:`${s.count/maxCount*100}%`}}/></div>
   <span>{s.count}× <small>{pct(s.pct)} dos {team.requested_games} jogos</small></span>
  </div>)}
 </section>
}

function CorrectScoreCard({data}:{data:MatchAnalysis}) {
 const cs=data.goals?.correct_score
 return <>
  {data.goals?.warning&&<p className="a3-warning">{data.goals.warning}</p>}
  {!cs?<section className="a3-panel"><h2>Correct Score</h2><p className="a3-note">Linha do tempo indisponível. Confirme os campos de `minutos_gols` e a relação com `jogos`.</p></section>:<>
   <div className="a3-cs-grid"><CorrectScoreTeam name={data.home} team={cs.home}/><CorrectScoreTeam name={data.away} team={cs.away}/></div>
   <p className="a3-note">Placar final: todos os jogos do intervalo (tabela jogos). Minutos por placar: tabela minutos_gols, apenas jogos com sequência completa. Jogo com 90 minutos; se o último gol saiu após os 90, o jogo termina 2 minutos depois dele. Acréscimos do 1º tempo contam como minuto 45.</p>
  </>}
 </>
}

function ProjectionView({data,market,setMarket,odd,setOdd,evRequested,setEvRequested,setError}:{
 data:MatchAnalysis;market:string;setMarket:(v:string)=>void;odd:string;setOdd:(v:string)=>void;
 evRequested:boolean;setEvRequested:(v:boolean)=>void;setError:(v:string)=>void}) {
 const pred=data.probabilities.find(p=>p.key===market)
 const oddNumber=Number(odd.replace(',','.'))
 const validOdd=odd.trim().length>0&&Number.isFinite(oddNumber)&&oddNumber>=1.01&&oddNumber<=1000
 const ev=evRequested&&pred?.probability!=null&&validOdd?
   (pred.kind==='lay'?100*((pred.probability/100)/(oddNumber-1)-(1-pred.probability/100)):
    100*((pred.probability/100)*oddNumber-1)):null
 const formattedOdd=()=>{if(validOdd)setOdd(oddNumber.toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2,useGrouping:false}))}
 const strength=data.projection?.radar
 const axes = [
   {field:'attack',label:'Ataque'},{field:'defense',label:'Defesa'},
   {field:'creativity',label:'Criatividade'},{field:'strength',label:'Força'}] as const
 return <>
  <section className="a3-panel"><h2>Projeção de forças · comparativo entre os clubes</h2>
   {strength&&<RadarChart axes={axes.map(axis=>({label:axis.label,a:strength.home[axis.field],b:strength.away[axis.field]}))}
      labelA={data.home} labelB={data.away} note="Índices relativos de 0 a 100, baseados nas médias recentes disponíveis. São índices heurísticos, não probabilidades de vitória."/>}
  </section>
  <section className="a3-panel"><h2>Gols esperados para o confronto</h2>
   <div className="a3-expected-grid"><div><small>{data.home}</small><strong>{n(data.expected_goals.home,2)}</strong><span>Gols esperados pelo modelo</span></div>
    <div><small>{data.away}</small><strong>{n(data.expected_goals.away,2)}</strong><span>Gols esperados pelo modelo</span></div></div>
   <p className="a3-note">Estimativa de xG e desempenho ofensivo/defensivo. Últimos jogos têm maior peso, com meia-vida de {data.method.half_life_days} dias.</p>
  </section>
  <section className="a3-panel"><h2>Projeção probabilística · simulação de {n(data.projection.simulation_count,0)} jogos</h2>
   <div className="a3-prob-grid">{data.probabilities.filter(p=>HIGHLIGHTS.includes(p.key)).map(p=><div key={p.key} className="a3-prob-card">
    <small>{p.label}</small><strong>{pct(p.probability)}</strong>
    <div className="a3-prob-track"><i style={{width:`${p.probability??0}%`}}/></div>
    <span>Simulação: {pct(data.projection.simulations[p.key])}</span>
    <span>Odd justa: {n(p.fair_odd,2)}</span></div>)}</div>
   <div className="a3-score-projections">
    <article><small>Placar mais provável</small><strong>{data.projection.most_likely.score}</strong><span>{pct(data.projection.most_likely.probability)}</span></article>
    <article><small>Placar menos provável (0×0 a 4×4)</small><strong>{data.projection.least_likely.score}</strong><span>{pct(data.projection.least_likely.probability)}</span></article>
    <article><small>Zebra vencer por 1×0</small><strong>{data.projection.zebra_one_zero.score}</strong><span>{pct(data.projection.zebra_one_zero.probability)} · {data.projection.zebra_one_zero.team}</span></article>
   </div>
   <p className="a3-note">As probabilidades estimadas são calculadas pelo modelo de gols; a simulação Monte Carlo é uma checagem numérica da distribuição. O placar menos provável é limitado a 0×0 até 4×4.</p>
   <p className="a3-note">Treinamento: {data.projection.ml.status==='trained'?'modelo ML aceito na validação temporal':'modelo base aplicado'}.
    {' '}Amostra: {data.projection.ml.training_games} jogos de treino e {data.projection.ml.validation_games} de validação.
    {data.projection.ml.baseline_log_loss!=null&&` · Log-loss Poisson: ${n(data.projection.ml.baseline_log_loss,3)}`}
    {data.projection.ml.model_log_loss!=null&&` · Log-loss ML: ${n(data.projection.ml.model_log_loss,3)}`}
    {data.projection.ml.reason&&` · ${data.projection.ml.reason}`}</p>
  </section>
  <section className="a3-panel"><h2>EV — Valor esperado da aposta</h2>
   <div className="a3-filters a3-ev-filters"><label>Mercado<select value={market} onChange={e=>{setMarket(e.target.value);setEvRequested(false)}}>
    {MARKET_GROUPS.map(([group,title])=><optgroup label={title} key={group}>{data.probabilities.filter(p=>p.group===group).map(p=><option key={p.key} value={p.key}>{p.label}{p.probability==null?' · sem dados':''}</option>)}</optgroup>)}
   </select></label>
    <label>Odd disponível<input value={odd} placeholder="Ex.: 2,10" inputMode="decimal" onChange={e=>{setOdd(e.target.value);setEvRequested(false)}} onBlur={formattedOdd}/></label>
    <button type="button" disabled={pred?.probability==null} onClick={()=>{if(validOdd){formattedOdd();setEvRequested(true);setError('')}else setError('Informe uma odd entre 1,01 e 1.000,00.')}}>Calcular EV</button>
   </div>
   {pred?.probability==null&&<p className="a3-note">Esse mercado não possui dados confiáveis suficientes para estimar a probabilidade.</p>}
   {ev!=null&&<div className={`a3-ev ${ev>0?'is-positive':'is-negative'}`}><strong>{ev>0?'EV estimado positivo':'EV estimado não positivo'} · {n(ev,2)}%</strong>
    <p>Probabilidade do modelo: {pct(pred?.probability)} · Odd oferecida: {n(oddNumber,2)} · Odd justa: {n(pred?.fair_odd,2)} · Retorno esperado por R$ 100: {ev.toLocaleString('pt-BR',{style:'currency',currency:'BRL'})}.</p>
    <small>{pred?.kind==='lay'?'Lay com responsabilidade fixa de R$ 100.':'Back com stake de R$ 100.'} EV positivo não confirma vantagem real sem calibração externa.</small></div>}
  </section>
  <section className="a3-panel"><h2>Qualidade da amostra e limitações</h2>
   <p className="a3-note">Fonte: {data.method.data_source}. Qualidade: {data.method.quality}. {data.method.home_games} jogos do mandante e {data.method.away_games} do visitante, com {data.method.xg_home_games}/{data.method.xg_away_games} jogos com xG. {data.method.h2h_games} confrontos diretos encontrados.</p>
   {data.method.warnings.map((warning,i)=><p className="a3-note" key={i}>• {warning}</p>)}
  </section>
 </>
}

/** Conteúdo das abas Geral / Gols / CS / Ataque / Defesa / Projeção. */
export function MatchAnalysisBody({data,tab,onError}:{data:MatchAnalysis;tab:AnalysisTab;onError?:(msg:string)=>void}) {
 const [market,setMarket]=useState('over_2_5_ft')
 const [odd,setOdd]=useState('')
 const [evRequested,setEvRequested]=useState(false)
 const setError=onError??(()=>{})
 useEffect(()=>{setEvRequested(false)},[data,tab])
 if(tab==='geral')return <><Scoreboard data={data}/><Comparison data={data} title="Indicadores gerais · comparação dos clubes (inclui xG)" items={data.comparison.filter(item=>GENERAL_KEYS.has(item.key))}/>
  <p className="a3-note">Para análise detalhada, selecione Gols, Ataque, Defesa ou Projeção.</p></>
 if(tab==='gols')return <GoalCard data={data}/>
 if(tab==='correct_score')return <CorrectScoreCard data={data}/>
 if(tab==='ataque')return <Comparison data={data} title="Ataque e produção ofensiva" items={data.comparison.filter(item=>ATTACK_KEYS.has(item.key))}/>
 if(tab==='defesa')return <Comparison data={data} title="Defesa e capacidade de contenção" items={data.comparison.filter(item=>DEFENCE_KEYS.has(item.key))}/>
 return <ProjectionView data={data} market={market} setMarket={setMarket} odd={odd} setOdd={setOdd} evRequested={evRequested} setEvRequested={setEvRequested} setError={setError}/>
}
