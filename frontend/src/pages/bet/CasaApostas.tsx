import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, query } from '../../api'
import { ANALYSIS_INTERVALS, ANALYSIS_TABS, AnalysisTab, MatchAnalysis, MatchAnalysisBody } from '../../components/MatchAnalysisViews'
import { brl, dateBr, num, odd, plClass } from './shared'

type Config={banca_inicial:number;banca_atual:number;stake_fixa:number|null;stake_travada:boolean;data_limite:string|null}
type Card={id:string;data:string;casa:string;fora:string;pais:string;campeonato:string;formato:string;rodada:string|null;odds_reais:boolean;
 linha_do_tempo:boolean;odds_fonte?:string|null;odds:{casa:number|null;empate:number|null;fora:number|null};odds_estimadas?:boolean}
type Fixture={pais:string;campeonatos:{campeonato:string;formato:string;rodada:string|null;jogos:Card[]}[]}
type Sel={key:string;label:string;back:number|null;lay:number|null;fonte:string|null}
type Market={key:string;label:string;status:string;selecoes:Sel[]}
type MarketsData={jogo:Card;minuto:number;placar:string;gol_anterior:number|null;proximo_gol:number|null;mercados:Market[];
 odds_estimadas:boolean;aviso_odds:string;lay_aviso:string;modelo:{gols_esperados_casa:number;gols_esperados_fora:number;base:string;detalhes:{rating_casa:number;rating_fora:number;jogos_casa:number;jogos_fora:number;media_gols_campeonato:number}|null}}
type Block={jogos?:number;vitorias?:number;empates?:number;derrotas?:number;gols_pro?:number;gols_contra?:number;over05?:number;over15?:number;
 over25?:number;under35?:number;btts?:number;sem_sofrer?:number;sem_marcar?:number;goleadas_pro?:number;goleadas_contra?:number}
type TeamStats={time:string;geral:Block;casa:Block;fora:Block;ultimos5:Block;ultimos10:Block;forma:string;placares_mais_comuns:{placar:string;jogos:number}[];
 gols_1t_pct:number|null;abriu_placar_pct:number|null;venceu_apos_abrir_pct:number|null;ultimos_jogos:{data:string;adversario:string;mando:string;placar:string}[]}
type StatsData={cutoff:string;jogo:Card;odds_iniciais:Record<string,number|null>;casa:TeamStats;fora:TeamStats;
 confrontos_diretos:{data:string;jogo:string;placar:string}[];aviso:string}
type Slip={market:string;marketLabel:string;selection:string;label:string;side:'back'|'lay';odd:number;source:string|null}
type Pending={id:number;jogo:string;mercado_nome:string;selecao_nome:string;lado:string;odd:number;stake:number;exposicao:number;minuto:number;status:string}
type Settled={id:number;resultado:string;lucro:number;odd:number;placar_final:string|null;mensagem?:string}

const TAB_STATS='stats'
const MARKET_TABS:{id:string;label:string;market:string;only?:string;backOnly?:boolean}[]=[
 {id:'match_odds',label:'Match Odds',market:'match_odds'},{id:'ou_0_5_ht',label:'Over 0,5 HT',market:'ou_0_5_ht'},
 {id:'ou_0_5',label:'Over 0,5 FT',market:'ou_0_5'},
 {id:'ou_1_5',label:'Over 1,5',market:'ou_1_5'},{id:'ou_2_5',label:'Over 2,5',market:'ou_2_5'},
 {id:'ou_3_5',label:'Under 3,5',market:'ou_3_5',backOnly:true},{id:'btts',label:'Ambos Marcam',market:'btts'},
 {id:'correct_score',label:'Correct Score',market:'correct_score'},
 {id:'goleada_home',label:'Lay Goleada Mandante',market:'goleada',only:'home'},
 {id:'goleada_away',label:'Lay Goleada Visitante',market:'goleada',only:'away'}]
const SCOPES:{id:keyof Pick<TeamStats,'geral'|'ultimos5'|'ultimos10'>|'mando';label:string}[]=[
 {id:'geral',label:'Geral (últimos 20)'},{id:'mando',label:'Mando (casa x fora)'},{id:'ultimos5',label:'Últimos 5'},{id:'ultimos10',label:'Últimos 10'}]

const validDate=(v:string)=>/^\d{4}-\d{2}-\d{2}$/.test(v)&&Number(v.slice(0,4))>=1990&&!Number.isNaN(Date.parse(v+'T12:00:00'))
const nextDay=(v:string)=>validDate(v)?dateBr(new Date(Date.parse(v+'T12:00:00')+864e5).toISOString()):'—'
const pct=(v?:number|null)=>v==null?'—':`${num(v,1)}%`

export default function CasaApostas({config,reloadConfig,coverage}:{config:Config;reloadConfig:()=>Promise<unknown>|void;coverage:{ano:number;jogos:number}[]}) {
 const [cutoff,setCutoff]=useState(config.data_limite||'2022-03-01')
 const [formato,setFormato]=useState('Liga')
 const [windowDays,setWindowDays]=useState(30)
 const [fixtures,setFixtures]=useState<Fixture[]>([])
 const [loadingList,setLoadingList]=useState(false)
 const [selected,setSelected]=useState<Card|null>(null)
 const [tab,setTab]=useState(TAB_STATS)
 const [minute,setMinute]=useState(0)
 const [markets,setMarkets]=useState<MarketsData|null>(null)
 const [stats,setStats]=useState<StatsData|null>(null)
 const [error,setError]=useState('')
 const [slip,setSlip]=useState<Slip|null>(null)
 const [stake,setStake]=useState('')
 const [pending,setPending]=useState<Pending[]>([])
 const [settled,setSettled]=useState<Settled|null>(null)
 const [placing,setPlacing]=useState(false)
 const [finalizing,setFinalizing]=useState<number|null>(null)
 const [openCountries,setOpenCountries]=useState<Record<string,boolean>>({})
 const seq=useRef(0)

 const loadPending=useCallback(()=>api<Pending[]>('/api/bet/apostas/pendentes').then(setPending).catch(()=>{}),[])
 useEffect(()=>{loadPending()},[loadPending])

 const loadFixtures=useCallback(async()=>{
  if(!validDate(cutoff))return
  setLoadingList(true);setError('')
  try{setFixtures(await api<Fixture[]>(`/api/bet/jogos?${query({data_limite:cutoff,formato,janela_dias:windowDays})}`))}
  catch(e:any){setError(e.message);setFixtures([])}finally{setLoadingList(false)}
 },[cutoff,formato,windowDays])
 useEffect(()=>{loadFixtures()},[loadFixtures])

 const changeCutoff=async(value:string)=>{
  setCutoff(value);setSelected(null);setSlip(null);setSettled(null)
  if(validDate(value)){try{await api('/api/bet/config',{method:'PUT',body:JSON.stringify({data_limite:value})});reloadConfig()}catch{/* mantém local */}}
 }
 const open=(card:Card)=>{setSelected(card);setTab(TAB_STATS);setMinute(0);setMarkets(null);setStats(null);setSlip(null);setSettled(null);setError('')}

 useEffect(()=>{
  if(!selected)return
  api<StatsData>(`/api/bet/jogo/${selected.id}/estatisticas?${query({data_limite:cutoff})}`).then(setStats).catch((e:Error)=>setError(e.message))
 },[selected,cutoff])

 useEffect(()=>{
  if(!selected)return
  const id=++seq.current
  const timer=setTimeout(()=>{
   api<MarketsData>(`/api/bet/jogo/${selected.id}/mercados?${query({minuto:minute,data_limite:validDate(cutoff)?cutoff:undefined})}`)
    .then(d=>{if(id===seq.current){setMarkets(d);setError('')}})
    .catch((e:Error)=>{if(id===seq.current)setError(e.message)})
  },250)
  return()=>clearTimeout(timer)
 },[selected,minute,cutoff])
 useEffect(()=>{setSlip(null)},[minute,selected])

 const amount=config.stake_travada&&config.stake_fixa?config.stake_fixa:Number(stake.replace(',','.'))
 useEffect(()=>{if(config.stake_travada&&config.stake_fixa)setStake(String(config.stake_fixa))},[config.stake_travada,config.stake_fixa])
 // Back: valor = stake. Lay: valor = risco (responsabilidade); stake Betfair = risco / (odd - 1).
 const isLay=slip?.side==='lay'
 const liability=slip&&amount>0?(isLay?amount:amount):0
 const betStake=slip&&amount>0&&slip.odd>1?(isLay?amount/(slip.odd-1):amount):0
 const profit=slip&&amount>0?(isLay?betStake:amount*(slip.odd-1)):0

 const pick=(m:Market,s:Sel,side:'back'|'lay')=>{
  const value=side==='back'?s.back:s.lay
  if(value==null||!selected)return
  setSettled(null)
  setSlip({market:m.key,marketLabel:m.label,selection:s.key,label:s.label,side,odd:value,source:s.fonte})
 }
 const place=async()=>{
  if(!slip||!selected)return
  if(!(amount>=0.1)){setError(isLay?'Informe um risco de pelo menos R$ 0,10.':'Informe uma stake de pelo menos R$ 0,10.');return}
  if(!(betStake>0)){setError('Odd inválida para calcular a aposta.');return}
  setPlacing(true);setError('');setSettled(null)
  try{
   await api<Pending>('/api/bet/apostas',{method:'POST',body:JSON.stringify({data_limite:cutoff,jogo_id:selected.id,mercado:slip.market,
    selecao:slip.selection,lado:slip.side,minuto:minute,stake:Math.round(betStake*100)/100})})
   setSlip(null);await loadPending()
  }catch(e:any){setError(e.message)}finally{setPlacing(false)}
 }
 const finalize=async(id:number)=>{
  setFinalizing(id);setError('');setSettled(null)
  try{
   const r=await api<Settled>(`/api/bet/apostas/${id}/finalizar`,{method:'POST'})
   setSettled(r);await loadPending();await reloadConfig()
  }catch(e:any){setError(e.message)}finally{setFinalizing(null)}
 }
 const setFixed=async(patch:Record<string,unknown>)=>{
  try{await api('/api/bet/config',{method:'PUT',body:JSON.stringify(patch)});await reloadConfig()}catch(e:any){setError(e.message)}
 }

 const goTo=(m:number|null)=>{if(m!=null)setMinute(Math.max(0,Math.min(90,m)))}
 const scoreChanged=markets!=null&&markets.placar!=='0-0'
 const tabDef=MARKET_TABS.find(t=>t.id===tab)
 const tabEstimated=!!markets&&!!tabDef&&markets.mercados.some(m=>m.key===tabDef.market&&m.selecoes.some(s=>(!tabDef.only||s.key===tabDef.only)&&s.fonte==='estimada'))
 const total=useMemo(()=>fixtures.reduce((a,f)=>a+f.campeonatos.reduce((b,c)=>b+c.jogos.length,0),0),[fixtures])

 return <div className="bf-exchange">
  <aside className="bf-tree" aria-label="Jogos por país">
   <div className="bf-side-head">Futebol</div>
   <div className="bf-tree-body">
    {fixtures.map(f=><div key={f.pais}>
     <button type="button" className="bf-tree-country" aria-expanded={!!openCountries[f.pais]} onClick={()=>setOpenCountries(o=>({...o,[f.pais]:!o[f.pais]}))}>
      <span>{openCountries[f.pais]?'▾':'▸'}</span>{f.pais}</button>
     {openCountries[f.pais]&&f.campeonatos.map(c=><div key={c.campeonato} className="bf-tree-comp">
      <em>{c.campeonato}{c.rodada&&c.rodada!=='-'?` · ${c.rodada}`:''}</em>
      {c.jogos.map(j=><button type="button" key={j.id} className={selected?.id===j.id?'on':''} onClick={()=>open(j)}>{j.casa} v {j.fora}</button>)}</div>)}
    </div>)}
    {!fixtures.length&&!loadingList&&<p className="bf-muted pad">Sem jogos a partir desta data.</p>}
   </div>
  </aside>

  <section className="bf-center">
   <div className="bf-toolbar">
    <label>Data limite<input type="date" value={cutoff} onChange={e=>changeCutoff(e.target.value)}/></label>
    <label>Competições<select value={formato} onChange={e=>{setFormato(e.target.value);setSelected(null)}}><option value="Liga">Somente ligas</option><option value="Copa">Somente copas</option><option value="Todos">Todas</option></select></label>
    <label>Próximo jogo em até<select value={windowDays} onChange={e=>{setWindowDays(Number(e.target.value));setSelected(null)}}>{[7,14,30,60,120].map(d=><option key={d} value={d}>{d} dias</option>)}</select></label>
    <p className="cov">Cobertura da tabela odds (jogos por ano): {coverage.map(c=>`${c.ano}: ${c.jogos}`).join(' · ')}. Datas fora desses períodos não têm jogos.</p>
    <p>Somente informações até <strong>{validDate(cutoff)?dateBr(cutoff):'—'}</strong>. Próxima rodada de cada campeonato a partir de {nextDay(cutoff)}.</p>
   </div>
   {error&&<p className="bf-alert err" role="alert">{error}</p>}
   {settled&&<p className={`bf-alert ${settled.resultado==='green'?'ok':'err'}`} role="status">
    Aposta finalizada: <strong>{settled.resultado.toUpperCase()}</strong> · placar final {settled.placar_final} · odd {odd(settled.odd)} · resultado {brl(settled.lucro)}</p>}

   {!selected?<>
    <h2 className="bf-h2">Próximos jogos {loadingList?'· carregando...':`· ${total} jogos`}</h2>
    {fixtures.map(f=><div key={f.pais} className="bf-event-group">
     <h3>{f.pais}</h3>
     {f.campeonatos.map(c=><table key={c.campeonato} className="bf-events"><thead><tr><th>{c.campeonato}{c.rodada&&c.rodada!=='-'?` · ${c.rodada}`:''}</th><th>1</th><th>X</th><th>2</th></tr></thead><tbody>
      {c.jogos.map(j=><tr key={j.id}>
       <td><button type="button" className="bf-link" onClick={()=>open(j)}><span className="d">{dateBr(j.data)}</span>{j.casa} <i>v</i> {j.fora}</button></td>
       <td className={`bk${j.odds_estimadas?' est':''}`} title={j.odds_estimadas?'Odd estimada pelo modelo':undefined}>{odd(j.odds.casa)}</td><td className={`bk${j.odds_estimadas?' est':''}`}>{odd(j.odds.empate)}</td><td className={`bk${j.odds_estimadas?' est':''}`}>{odd(j.odds.fora)}</td></tr>)}</tbody></table>)}</div>)}
   </>:<>
    <div className="bf-event-head">
     <button type="button" className="bf-link back" onClick={()=>{setSelected(null);setSlip(null)}}>‹ Todos os jogos</button>
     <h2>{selected.casa} <i>v</i> {selected.fora}</h2>
     <p>{selected.pais} · {selected.campeonato}{selected.rodada&&selected.rodada!=='-'?` · ${selected.rodada}`:''} · {dateBr(selected.data)}</p>
     <div className="bf-scorebox" aria-live="polite"><span>{selected.casa}</span><strong>{markets?.placar.replace('-',' - ')??'0 - 0'}</strong><span>{selected.fora}</span><em>{minute}'</em></div>
    </div>
    <nav className="bf-market-tabs" aria-label="Mercados">
     <button type="button" className={tab===TAB_STATS?'on':''} onClick={()=>setTab(TAB_STATS)}>Estatísticas</button>
     {MARKET_TABS.map(t=><button type="button" key={t.id} className={tab===t.id?'on':''} onClick={()=>setTab(t.id)}>{t.label}</button>)}</nav>

    {tab===TAB_STATS?<StatsPanel stats={stats} game={selected}/>:<>
     <div className="bf-minute">
      <label>Minutos
       <span className="bf-stepper"><button type="button" aria-label="Menos um minuto" onClick={()=>goTo(minute-1)}>−</button>
        <input type="number" min={0} max={90} value={minute} disabled={!selected.linha_do_tempo&&minute===0&&false}
         onChange={e=>goTo(e.target.value===''?0:Number(e.target.value))}/>
        <button type="button" aria-label="Mais um minuto" onClick={()=>goTo(minute+1)}>+</button></span></label>
      {!selected.linha_do_tempo&&<span className="bf-tag warn">Sem minutos dos gols: operar apenas no minuto 0</span>}
      {scoreChanged&&<button type="button" className="bf-btn small" onClick={()=>goTo(markets?.proximo_gol??90)}>Mostrar próximo gol</button>}
     </div>
     {tabEstimated&&<p className="bf-alert warn">⚠ {markets?.aviso_odds} {markets?.lay_aviso}</p>}
     {markets&&!tabEstimated&&<p className="bf-hint">Odds Back reais da tabela {markets.jogo.odds_fonte||'odds'}. {markets.lay_aviso}</p>}
     {markets&&tabDef&&markets.mercados.filter(m=>m.key===tabDef.market).map(m=>{
      const backOnly=!!tabDef.backOnly||!!(m as {back_only?:boolean}).back_only
      return <table className="bf-market" key={m.key}>
      <thead><tr><th><span className="status">{m.status}</span> {tabDef.label}</th><th className="hd">Back</th>{!backOnly&&<th className="hd">Lay</th>}</tr></thead>
      <tbody>{m.selecoes.filter(s=>!tabDef.only||s.key===tabDef.only).map(s=><tr key={s.key}>
       <td className="nm">{s.key==='home'&&m.key==='match_odds'?selected.casa:s.key==='away'&&m.key==='match_odds'?selected.fora:s.label}
        {s.fonte==='estimada'&&<span className="bf-tag warn" title="Odd estimada pelo modelo">est.</span>}</td>
       <td><button type="button" className={`bk${slip&&slip.market===m.key&&slip.selection===s.key&&slip.side==='back'?' sel':''}`} disabled={s.back==null} onClick={()=>pick(m,s,'back')}>{s.back==null?'—':odd(s.back)}</button></td>
       {!backOnly&&<td><button type="button" className={`ly${slip&&slip.market===m.key&&slip.selection===s.key&&slip.side==='lay'?' sel':''}`} disabled={s.lay==null} onClick={()=>pick(m,s,'lay')}>{s.lay==null?'—':odd(s.lay)}</button></td>}
      </tr>)}</tbody></table>})}
     {markets&&<p className="bf-muted">Modelo: gols esperados {num(markets.modelo.gols_esperados_casa)} x {num(markets.modelo.gols_esperados_fora)} (base: {markets.modelo.base==='odds'?'odds iniciais':'força dos clubes'}){markets.modelo.detalhes&&<> · Elo {markets.modelo.detalhes.rating_casa} x {markets.modelo.detalhes.rating_fora} · média de gols do campeonato {num(markets.modelo.detalhes.media_gols_campeonato)}{(markets.modelo.detalhes.jogos_casa===0||markets.modelo.detalhes.jogos_fora===0)&&' · clube sem histórico nas bases: força estimada como divisão inferior'}</>}.</p>}
    </>}
   </>}
  </section>

  <aside className="bf-slip" aria-label="Boletim de apostas">
   <div className="bf-side-head">Boletim de apostas</div>
   <div className="bf-bank"><div><small>Banca</small><strong>{brl(config.banca_atual)}</strong></div>
    <div><small>Lucro/Prejuízo</small><strong className={plClass(config.banca_atual-config.banca_inicial)}>{brl(config.banca_atual-config.banca_inicial)}</strong></div></div>
   {!slip?<p className="bf-muted pad">Clique em uma odd azul (Back) ou rosa (Lay) para montar a aposta.</p>:<div className={`bf-slip-item ${slip.side}`}>
    <header><strong>{slip.side==='back'?'Back':'Lay'}</strong> {slip.label}<button type="button" aria-label="Remover" onClick={()=>setSlip(null)}>×</button></header>
    <p className="mk">{slip.marketLabel} · {selected?.casa} v {selected?.fora} · {minute}'</p>
    {slip.source==='estimada'&&<p className="est">Odd estimada pelo modelo</p>}
    <div className="row"><label>Odd<input readOnly value={odd(slip.odd)}/></label>
     <label>{isLay?'Risco (R$)':'Stake (R$)'}<input inputMode="decimal" value={config.stake_travada&&config.stake_fixa?String(config.stake_fixa):stake} disabled={config.stake_travada&&!!config.stake_fixa} onChange={e=>setStake(e.target.value)} placeholder="0,00"/></label></div>
    <dl><dt>{isLay?'Lucro se ganhar':'Lucro'}</dt><dd className="bf-pos">{brl(profit)}</dd><dt>{isLay?'Risco (a perder)':'Responsabilidade'}</dt><dd className="bf-neg">{brl(liability)}</dd></dl>
    <button type="button" className="bf-btn place" disabled={placing||!(amount>=0.1)||!(betStake>0)} onClick={place}>{placing?'Abrindo...':'Abrir entrada'}</button></div>}
   <div className="bf-pending">
    <h3>Entradas pendentes {pending.length?`· ${pending.length}`:''}</h3>
    {!pending.length?<p className="bf-muted pad">Nenhuma entrada aberta. Ao apostar, ela fica aqui até você finalizar.</p>:
     pending.map(p=><div key={p.id} className={`bf-pending-item ${p.lado}`}>
      <div><strong>{p.lado==='back'?'Back':'Lay'}</strong> {p.selecao_nome}<small>{p.mercado_nome} · {p.jogo} · {p.minuto}'</small>
       <em>Odd {odd(p.odd)} · risco {brl(p.exposicao)}</em></div>
      <button type="button" className="bf-btn small primary" disabled={finalizing!=null} onClick={()=>finalize(p.id)}>
       {finalizing===p.id?'Finalizando...':'Finalizar'}</button></div>)}
   </div>
   <div className="bf-fixed"><label><input type="checkbox" checked={config.stake_travada} onChange={e=>setFixed({stake_travada:e.target.checked,...(e.target.checked&&!config.stake_fixa&&amount>0?{stake_fixa:amount}:{})})}/> Fixar valor <small className="bf-muted">(stake no Back · risco no Lay)</small></label>
    <input inputMode="decimal" aria-label="Valor fixo" placeholder="R$" defaultValue={config.stake_fixa??''} key={config.stake_fixa??'none'}
     onBlur={e=>{const v=e.target.value.replace(',','.');if(v!==String(config.stake_fixa??''))setFixed({stake_fixa:v||null})}}/></div>
  </aside>
 </div>
}

function StatsPanel({stats,game}:{stats:StatsData|null;game:Card}) {
 const [mainTab,setMainTab]=useState<'resumo'|AnalysisTab>('resumo')
 const [scope,setScope]=useState<'geral'|'mando'|'ultimos5'|'ultimos10'>('geral')
 const [intervalGames,setIntervalGames]=useState(20)
 const [analysis,setAnalysis]=useState<MatchAnalysis|null>(null)
 const [analysisLoading,setAnalysisLoading]=useState(false)
 const [analysisError,setAnalysisError]=useState('')

 useEffect(()=>{
  let active=true
  setAnalysis(null);setAnalysisError('');setAnalysisLoading(true)
  api<MatchAnalysis>('/api/analysis-v3/match/analyze',{method:'POST',body:JSON.stringify({
   country:game.pais||null,competition:null,home:game.casa,away:game.fora,interval_games:intervalGames})})
   .then(d=>{if(active)setAnalysis(d)})
   .catch((e:Error)=>{if(active)setAnalysisError(e.message)})
   .finally(()=>{if(active)setAnalysisLoading(false)})
  return()=>{active=false}
 },[game.id,game.casa,game.fora,game.pais,intervalGames])

 if(!stats)return <p className="bf-muted pad">Carregando estatísticas...</p>
 const pick=(t:TeamStats,isHome:boolean):Block=>scope==='mando'?(isHome?t.casa:t.fora):t[scope]
 const h=pick(stats.casa,true),a=pick(stats.fora,false)
 const rows:[string,(b:Block)=>string][]=[
  ['Jogos',b=>String(b.jogos??0)],['V - E - D',b=>b.jogos?`${b.vitorias} - ${b.empates} - ${b.derrotas}`:'—'],
  ['Gols marcados / jogo',b=>b.jogos?num(b.gols_pro):'—'],['Gols sofridos / jogo',b=>b.jogos?num(b.gols_contra):'—'],
  ['Over 0,5',b=>pct(b.over05)],['Over 1,5',b=>pct(b.over15)],['Over 2,5',b=>pct(b.over25)],['Under 3,5',b=>pct(b.under35)],
  ['Ambos marcam',b=>pct(b.btts)],['Sem sofrer gol',b=>pct(b.sem_sofrer)],['Sem marcar gol',b=>pct(b.sem_marcar)],
  ['Goleadas a favor / contra',b=>b.jogos?`${b.goleadas_pro} / ${b.goleadas_contra}`:'—']]
 const o=stats.odds_iniciais
 const analysisTabs:({id:'resumo';label:string}|typeof ANALYSIS_TABS[number])[]=[{id:'resumo',label:'Resumo'},...ANALYSIS_TABS]
 return <div className="bf-stats-panel">
  <p className="bf-alert info">{stats.aviso}</p>
  <div className="bf-odds-strip"><span>Odds iniciais</span><b>1 · {odd(o.odd_casa_ft)}</b><b>X · {odd(o.odd_empate_ft)}</b><b>2 · {odd(o.odd_fora_ft)}</b>
   <b>Over 2,5 · {odd(o.over_2_5_ft)}</b><b>Under 2,5 · {odd(o.under_2_5_ft)}</b><b>Ambos · {odd(o.ambos_marcam_sim)}</b></div>
  <nav className="a3-analysis-tabs bf-analysis-tabs" aria-label="Categorias das estatísticas">
   {analysisTabs.map(t=><button type="button" key={t.id} className={mainTab===t.id?'selected':''} onClick={()=>setMainTab(t.id)}>{t.label}</button>)}
  </nav>
  {mainTab!=='resumo'&&<div className="bf-form inline"><label>Últimos jogos por clube<select value={intervalGames} onChange={e=>setIntervalGames(Number(e.target.value))}>
   {ANALYSIS_INTERVALS.map(i=><option key={i} value={i}>{i} jogos</option>)}</select></label>
   {analysisLoading&&<span className="bf-muted">Calculando xG e projeções…</span>}</div>}
  {mainTab==='resumo'?<>
   <div className="bf-seg" role="group" aria-label="Recorte">{SCOPES.map(s=><button type="button" key={s.id} className={scope===s.id?'on':''} onClick={()=>setScope(s.id as typeof scope)}>{s.label}</button>)}</div>
   <table className="bf-table versus"><thead><tr><th>{stats.casa.time}</th><th>Indicador</th><th>{stats.fora.time}</th></tr></thead><tbody>
    <tr><td><Form value={stats.casa.forma}/></td><td>Forma recente</td><td><Form value={stats.fora.forma}/></td></tr>
    {rows.map(([label,fn])=><tr key={label}><td>{fn(h)}</td><td>{label}</td><td>{fn(a)}</td></tr>)}
    <tr><td>{pct(stats.casa.gols_1t_pct)}</td><td>Gols no 1º tempo</td><td>{pct(stats.fora.gols_1t_pct)}</td></tr>
    <tr><td>{pct(stats.casa.abriu_placar_pct)}</td><td>Abriu o placar</td><td>{pct(stats.fora.abriu_placar_pct)}</td></tr>
    <tr><td>{pct(stats.casa.venceu_apos_abrir_pct)}</td><td>Venceu após abrir o placar</td><td>{pct(stats.fora.venceu_apos_abrir_pct)}</td></tr>
    <tr><td>{stats.casa.placares_mais_comuns.map(p=>`${p.placar} (${p.jogos}x)`).join(' · ')||'—'}</td><td>Placares mais comuns (clube-adversário)</td><td>{stats.fora.placares_mais_comuns.map(p=>`${p.placar} (${p.jogos}x)`).join(' · ')||'—'}</td></tr></tbody></table>
   <div className="bf-two">
    {[stats.casa,stats.fora].map(t=><div key={t.time}><h4>Últimos jogos · {t.time}</h4>
     <table className="bf-table dense"><tbody>{t.ultimos_jogos.map((g,i)=><tr key={i}><td>{dateBr(g.data)}</td><td>{g.mando==='C'?'vs':'@'} {g.adversario}</td><td>{g.placar}</td></tr>)}
      {!t.ultimos_jogos.length&&<tr><td className="bf-muted">Sem jogos anteriores à data limite.</td></tr>}</tbody></table></div>)}
   </div>
   <h4>Confrontos diretos (até a data limite)</h4>
   {stats.confrontos_diretos.length?<table className="bf-table dense"><tbody>{stats.confrontos_diretos.map((g,i)=><tr key={i}><td>{dateBr(g.data)}</td><td>{g.jogo}</td><td>{g.placar}</td></tr>)}</tbody></table>:<p className="bf-muted">Sem confrontos registrados.</p>}
  </>:<>
   {analysisError&&<p className="bf-alert err" role="alert">{analysisError}</p>}
   {!analysis&&!analysisError&&analysisLoading&&<p className="bf-muted pad">Carregando análise SofaScore (xG, ataque, defesa, projeção)…</p>}
   {analysis&&mainTab!=='resumo'&&<div className="bf-analysis-embed"><MatchAnalysisBody data={analysis} tab={mainTab} onError={setAnalysisError}/></div>}
  </>}
 </div>
}

function Form({value}:{value:string}) {
 return <span className="bf-form-badges">{value.split('').map((c,i)=><i key={i} className={c==='V'?'w':c==='E'?'d':'l'}>{c}</i>)}{!value&&'—'}</span>
}
