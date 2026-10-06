import { useEffect, useMemo, useState } from 'react'
import { api, query } from '../api'
import Autocomplete from '../components/Autocomplete'
import IdAutocomplete from '../components/IdAutocomplete'
import Modal from '../components/Modal'
import RadarChart from '../components/RadarChart'
import StatBar from '../components/StatBar'
import MarketValueEvolution from '../components/MarketValueEvolution'

type Item={id:number;nome:string;escudo_url?:string;pais?:string;principal?:boolean}
type FilterOptions={competitions:Item[];seasons:string[];opponents:string[]}
const fmt=(v:any,d=1)=>v===null||v===undefined?'—':Number(v).toLocaleString('pt-BR',{minimumFractionDigits:d,maximumFractionDigits:d})
const datePt=(v?:string)=>v?new Date(`${v}T12:00:00`).toLocaleDateString('pt-BR'):'—'

function BlowoutTable({title,rows}:{title:string;rows:any[]}){
 return <div className="panel pad blowout-panel"><h3>{title}</h3><div className="table-scroll"><table className="blowout-table"><thead><tr><th>#</th><th>Data</th><th>Adversário</th><th>Placar</th><th>Saldo</th><th>Mando</th><th>Competição</th></tr></thead><tbody>{rows?.length?rows.map((g:any,i:number)=><tr key={`${g.date}-${g.opponent}-${i}`}><td>{i+1}</td><td>{datePt(g.date)}</td><td><strong>{g.opponent}</strong></td><td><strong>{g.score}</strong></td><td>{g.goal_diff}</td><td>{g.venue==='home'?'Mandante':'Visitante'}</td><td>{g.competition||'—'}</td></tr>):<tr><td colSpan={7} className="empty-row">Nenhum jogo no recorte.</td></tr>}</tbody></table></div></div>
}

export default function Clubes(){
 const[countries,setCountries]=useState<Item[]>([])
 const[country,setCountry]=useState<Item|null>(null)
 const[clubs,setClubs]=useState<Item[]>([])
 const[selected,setSelected]=useState<Item|null>(null)
 const[stats,setStats]=useState<any>(null)
 const[search,setSearch]=useState('')
 const[filters,setFilters]=useState<FilterOptions>({competitions:[],seasons:[],opponents:[]})
 const[competition,setCompetition]=useState<Item|null>(null)
 const[season,setSeason]=useState('')
 const[opponent,setOpponent]=useState('')
 const[venue,setVenue]=useState('all')
 const[resultFilter,setResultFilter]=useState('all')
 const[oddGamesOpen,setOddGamesOpen]=useState(false)
 const[marketEvolution,setMarketEvolution]=useState<any>(null)
 const[loading,setLoading]=useState(false)

 useEffect(()=>{api<Item[]>('/api/countries').then(setCountries)},[])
 useEffect(()=>{api<Item[]>(`/api/club-directory${country?`?country_id=${country.id}`:''}`).then(d=>{setClubs(d);if(selected&&!d.some(x=>x.id===selected.id)){setSelected(null);setStats(null);setMarketEvolution(null)}})},[country?.id])

 useEffect(()=>{
   if(!selected){setFilters({competitions:[],seasons:[],opponents:[]});return}
   api<FilterOptions>(`/api/club-directory/${selected.id}/filters?${query({competition_id:competition?.id,season:season||undefined,venue})}`).then(setFilters)
 },[selected?.id,competition?.id,season,venue])

 useEffect(()=>{
   if(!selected)return
   setLoading(true)
   api<any>(`/api/club-directory/${selected.id}/stats?${query({competition_id:competition?.id,season:season||undefined,opponent:opponent||undefined,venue,result_filter:resultFilter})}`)
     .then(setStats)
     .finally(()=>setLoading(false))
 },[selected?.id,competition?.id,season,opponent,venue,resultFilter])

 useEffect(()=>{
   if(!selected){setMarketEvolution(null);return}
   api<any>(`/api/club-directory/${selected.id}/market-value-evolution?${query({competition_id:competition?.id,season:season||undefined})}`)
     .then(setMarketEvolution)
 },[selected?.id,competition?.id,season])

 const visible=useMemo(()=>clubs.filter(c=>c.nome.toLowerCase().includes(search.toLowerCase())).sort((a,b)=>a.nome.localeCompare(b.nome,'pt-BR')),[clubs,search])
 const strength=stats?.strength_profile
 const radarAxes=strength?[
   {label:'Ataque histórico',a:strength.club.historical_attack,b:strength.peers.historical_attack},
   {label:'Defesa histórica',a:strength.club.historical_defense,b:strength.peers.historical_defense,lowerBetter:true},
   {label:`Ataque ${strength.current_season}`,a:strength.club.current_attack,b:strength.peers.current_attack},
   {label:`Defesa ${strength.current_season}`,a:strength.club.current_defense,b:strength.peers.current_defense,lowerBetter:true},
 ]:[]

 function chooseClub(c:Item){
   setSelected(c);setStats(null);setMarketEvolution(null);setCompetition(null);setSeason('');setOpponent('');setVenue('all');setResultFilter('all');setOddGamesOpen(false)
 }

 return <section className="page"><div className="page-header"><div><span className="eyebrow">TEAM DATABASE</span><h1>Clubes</h1><p>Perfil consolidado e indicadores históricos dos clubes cadastrados.</p></div></div><div className="filter-strip clubs-filter"><IdAutocomplete label="País" value={country} options={countries} onChange={setCountry}/><div className="field"><label>Buscar clube</label><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Digite o nome..."/></div></div>
  {!selected?<div className="club-directory">{visible.map(c=><button key={c.id} className="club-card" onClick={()=>chooseClub(c)}>{c.escudo_url?<img src={c.escudo_url}/>:<span className="club-placeholder">{c.nome[0]}</span>}<strong>{c.nome}</strong><span>{c.pais}</span></button>)}</div>:<>
   <button className="back-link" onClick={()=>{setSelected(null);setStats(null);setMarketEvolution(null)}}>← Voltar aos clubes</button>
   <div className="club-profile-head panel"><div className="club-profile-identity">{selected.escudo_url?<img src={selected.escudo_url}/>:<span className="club-placeholder large">{selected.nome[0]}</span>}<div><span className="eyebrow">CLUB PROFILE</span><h2>{selected.nome}</h2><p>{selected.pais}</p></div></div>{stats&&<div className="club-head-kpis"><span><small>Jogos</small><strong>{stats.games.toLocaleString('pt-BR')}</strong></span><span><small>Aproveitamento</small><strong>{fmt(stats.performance_pct,1)}%</strong></span><span><small>Maior ELO</small><strong>{stats.max_elo?fmt(stats.max_elo,1):'—'}</strong></span></div>}</div>

   <div className="panel club-profile-filters">
    <IdAutocomplete label="Campeonato" value={competition} options={filters.competitions} onChange={v=>{setCompetition(v);setSeason('');setOpponent('')}}/>
    <div className="field"><label>Temporada</label><select value={season} onChange={e=>{setSeason(e.target.value);setOpponent('')}}><option value="">Todas</option>{filters.seasons.map(s=><option key={s}>{s}</option>)}</select></div>
    <Autocomplete label="Adversário" value={opponent} options={filters.opponents} onChange={setOpponent} placeholder="Todos os adversários"/>
    <div className="field"><label>Mando de campo</label><select value={venue} onChange={e=>{setVenue(e.target.value);setOpponent('')}}><option value="all">Todos</option><option value="home">Mandante</option><option value="away">Visitante</option></select></div>
    <div className="field"><label>Resultado</label><select value={resultFilter} onChange={e=>setResultFilter(e.target.value)}><option value="all">Todos</option><option value="win">Vitória</option><option value="draw">Empate</option><option value="loss">Derrota</option></select></div>
    <button className="secondary clear-profile-filter" onClick={()=>{setCompetition(null);setSeason('');setOpponent('');setVenue('all');setResultFilter('all')}}>Limpar filtros</button>
   </div>

   {loading&&<div className="notice info">Atualizando perfil...</div>}
   {stats&&<>
    <div className="club-detail-grid">
     <div className="panel pad"><h3>Resultados</h3><StatBar label="Vitórias" value={stats.wins_pct} suffix="%"/><StatBar label="Empates" value={stats.draws_pct} suffix="%"/><StatBar label="Derrotas" value={stats.losses_pct} suffix="%"/><div className="numeric-stats"><span><small>Vitórias</small><strong>{stats.wins.toLocaleString('pt-BR')}</strong></span><span><small>Empates</small><strong>{stats.draws.toLocaleString('pt-BR')}</strong></span><span><small>Derrotas</small><strong>{stats.losses.toLocaleString('pt-BR')}</strong></span><span><small>Gols marcados</small><strong>{stats.goals_for.toLocaleString('pt-BR')}</strong></span><span><small>Gols sofridos</small><strong>{stats.goals_against.toLocaleString('pt-BR')}</strong></span><span><small>Média gols marcados</small><strong>{fmt(stats.avg_goals_for,2)}</strong></span><span><small>Média gols sofridos</small><strong>{fmt(stats.avg_goals_against,2)}</strong></span></div></div>
     <div className="panel pad"><h3>Mercados de gols</h3><StatBar label="Over 0,5" value={stats.over_05_pct} suffix="%"/><StatBar label="Over 1,5" value={stats.over_15_pct} suffix="%"/><StatBar label="Over 2,5" value={stats.over_25_pct} suffix="%"/><StatBar label="Over 3,5" value={stats.over_35_pct} suffix="%"/><StatBar label="Ambos marcam" value={stats.btts_pct} suffix="%"/></div>
     <div className="panel pad"><h3>Custo do gol</h3><div className="numeric-stats two"><span><small>Custo do gol 1.0</small><strong>{fmt(stats.cost_goal_1,2)}</strong></span><span><small>CV custo do gol 1.0</small><strong>{stats.cv_cost_goal_1?`${fmt(stats.cv_cost_goal_1,1)}%`:'—'}</strong></span><span><small>Custo do gol 2.0</small><strong>{fmt(stats.cost_goal_2,2)}</strong></span><span><small>CV custo do gol 2.0</small><strong>{stats.cv_cost_goal_2?`${fmt(stats.cv_cost_goal_2,1)}%`:'—'}</strong></span></div>{!stats.has_odds&&<div className="notice info">Sem odds conciliadas: os indicadores de custo do gol permanecem vazios.</div>}</div>
     <div className="panel pad odds-panel"><h3>Odds</h3><div className="numeric-stats odds-stats"><span><small>Odd média das vitórias</small><strong>{fmt(stats.avg_win_odd,2)}</strong></span><button className="odds-band-button" disabled={!stats.winning_odd_band} onClick={()=>setOddGamesOpen(true)}><small>Faixa de odds que mais vence</small><strong>{stats.winning_odd_band?.label||'—'}</strong>{stats.winning_odd_band&&<em>{stats.winning_odd_band.wins.toLocaleString('pt-BR')} vitórias · {fmt(stats.winning_odd_band.win_pct,1)}%</em>}<i>Ver jogos →</i></button><span><small>Maior odd vencedora</small><strong>{fmt(stats.max_win_odd,2)}</strong>{stats.max_win_odd_game&&<em>{stats.max_win_odd_game.opponent} · {stats.max_win_odd_game.score}{stats.max_win_odd_game.date?` · ${datePt(stats.max_win_odd_game.date)}`:''}</em>}</span><span><small>Odd média em jogos Over 2,5</small><strong>{fmt(stats.avg_odd_over_25,2)}</strong></span></div>{!stats.has_odds&&<div className="notice info">Importe e concilie as odds 1X2 para preencher esta seção.</div>}</div>
    </div>

    {strength&&<div className="panel pad section-space club-radar-section"><div className="panel-title"><div><h2>Força ofensiva e defensiva</h2><span>{strength.competition} · referência {strength.current_season}{strength.used_fallback_season?` (última temporada com jogos até ${strength.requested_season})`:''}</span></div><span>Defesa: quanto menor o índice, melhor.</span></div><RadarChart axes={radarAxes} labelA={selected.nome} labelB="Média dos demais clubes" note="1,00 representa a média da competição. A força defensiva mede gols concedidos relativos à liga: abaixo de 1,00 é melhor. No radar, os eixos defensivos são invertidos apenas visualmente para que uma área maior represente desempenho melhor; os números exibidos continuam sendo os índices originais."/></div>}

    <div className="blowout-grid section-space"><BlowoutTable title="10 maiores goleadas aplicadas" rows={stats.biggest_wins||[]}/><BlowoutTable title="10 maiores goleadas sofridas" rows={stats.biggest_losses||[]}/></div>

    <MarketValueEvolution data={marketEvolution} clubName={selected.nome}/>
   </>}

   {oddGamesOpen&&stats?.winning_odd_band&&<Modal title={`Vitórias na faixa ${stats.winning_odd_band.label}`} onClose={()=>setOddGamesOpen(false)}><div className="odds-band-summary"><strong>{stats.winning_odd_band.wins.toLocaleString('pt-BR')} vitórias</strong><span>{fmt(stats.winning_odd_band.win_pct,1)}% de aproveitamento em {stats.winning_odd_band.games.toLocaleString('pt-BR')} jogos dentro da faixa.</span></div><div className="table-scroll"><table><thead><tr><th>Data</th><th>Adversário</th><th>Placar</th><th>Odd</th><th>Mando</th><th>Competição</th><th>Temporada</th></tr></thead><tbody>{stats.winning_odd_band.games_detail.map((g:any,i:number)=><tr key={`${g.date}-${g.opponent}-${i}`}><td>{datePt(g.date)}</td><td><strong>{g.opponent}</strong></td><td>{g.score}</td><td><strong>{fmt(g.odd,2)}</strong></td><td>{g.venue==='home'?'Mandante':'Visitante'}</td><td>{g.competition||'—'}</td><td>{g.season||'—'}</td></tr>)}</tbody></table></div></Modal>}
  </>}
 </section>
}
