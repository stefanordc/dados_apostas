import { useEffect, useMemo, useState } from 'react'
import { api, query } from '../api'
import Autocomplete from '../components/Autocomplete'
import IdAutocomplete from '../components/IdAutocomplete'
import Modal from '../components/Modal'
import RadarChart from '../components/RadarChart'
import StatBar from '../components/StatBar'
import MarketValueEvolution from '../components/MarketValueEvolution'
import Tooltip from '../components/Tooltip'

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
 const[strength,setStrength]=useState<any>(null)
 const[strengthLoading,setStrengthLoading]=useState(false)
 const[loading,setLoading]=useState(false)
 const[page,setPage]=useState(1)
 const pageSize=60

 useEffect(()=>{api<Item[]>('/api/countries?with_games=true').then(setCountries)},[])
 useEffect(()=>{api<Item[]>(`/api/club-directory${country?`?country_id=${country.id}`:''}`).then(d=>{setClubs(d);if(selected&&!d.some(x=>x.id===selected.id)){setSelected(null);setStats(null);setMarketEvolution(null);setStrength(null)}})},[country?.id])

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
   if(!selected){setStrength(null);return}
   setStrengthLoading(true)
   setStrength(null)
   api<any>(`/api/club-directory/${selected.id}/strength-profile?${query({competition_id:competition?.id,season:season||undefined})}`)
     .then(setStrength)
     .finally(()=>setStrengthLoading(false))
 },[selected?.id,competition?.id,season])

 useEffect(()=>{
   if(!selected){setMarketEvolution(null);return}
   // O gráfico de mercado é secundário: aguarda as estatísticas principais.
   // Assim o perfil aparece primeiro e a consulta seguinte aproveita o cache do histórico.
   if(!stats)return
   api<any>(`/api/club-directory/${selected.id}/market-value-evolution?${query({competition_id:competition?.id,season:season||undefined})}`)
     .then(setMarketEvolution)
 },[selected?.id,competition?.id,season,stats])

 const visible=useMemo(()=>clubs.filter(c=>c.nome.toLowerCase().includes(search.toLowerCase())).sort((a,b)=>a.nome.localeCompare(b.nome,'pt-BR')),[clubs,search])
 const totalPages=Math.max(1,Math.ceil(visible.length/pageSize))
 const pagedVisible=visible.slice((page-1)*pageSize,page*pageSize)
 useEffect(()=>{setPage(1)},[country?.id,search])
 useEffect(()=>{if(page>totalPages)setPage(totalPages)},[page,totalPages])
 const radarAxes=strength?[
   {label:'Ataque histórico',a:strength.club.historical_attack,b:strength.peers.historical_attack},
   {label:'Defesa histórica',a:strength.club.historical_defense,b:strength.peers.historical_defense,lowerBetter:true},
   {label:`Ataque ${strength.current_season}`,a:strength.club.current_attack,b:strength.peers.current_attack},
   {label:`Defesa ${strength.current_season}`,a:strength.club.current_defense,b:strength.peers.current_defense,lowerBetter:true},
 ]:[]

 function chooseClub(c:Item){
   setSelected(c);setStats(null);setMarketEvolution(null);setStrength(null);setCompetition(null);setSeason('');setOpponent('');setVenue('all');setResultFilter('all');setOddGamesOpen(false)
 }

 return <section className="page"><div className="page-header"><div><span className="eyebrow">TEAM DATABASE</span><h1>Clubes</h1><p>Perfil consolidado e indicadores históricos dos clubes cadastrados.</p></div></div><div className="filter-strip clubs-filter"><IdAutocomplete label="País" value={country} options={countries} onChange={setCountry}/><div className="field"><label>Buscar clube</label><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Digite o nome..."/></div></div>
  {!selected?<><div className="club-directory">{pagedVisible.map(c=><button key={c.id} className="club-card" onClick={()=>chooseClub(c)}>{c.escudo_url?<img src={c.escudo_url}/>:<span className="club-placeholder">{c.nome[0]}</span>}<strong>{c.nome}</strong><span>{c.pais}</span></button>)}</div><div className="directory-pagination"><span>{visible.length.toLocaleString('pt-BR')} clubes · página {page} de {totalPages}</span><div><button className="secondary" disabled={page<=1} onClick={()=>setPage(p=>p-1)}>← Anterior</button><button className="secondary" disabled={page>=totalPages} onClick={()=>setPage(p=>p+1)}>Próxima →</button></div></div></>:<>
   <button className="back-link" onClick={()=>{setSelected(null);setStats(null);setMarketEvolution(null);setStrength(null)}}>← Voltar aos clubes</button>
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
     <div className="panel pad"><h3>Custo do gol</h3><div className="numeric-stats two"><span><small>Custo do gol 1.0 <Tooltip text="Indicador de custo associado ao primeiro gol no histórico do clube. Valores menores sugerem que o primeiro gol aparece com menor custo estatístico. Interprete junto com o CV: custo baixo com CV alto é menos estável."/></small><strong>{fmt(stats.cost_goal_1,2)}</strong></span><span><small>CV custo do gol 1.0 <Tooltip text="Coeficiente de variação do Custo do Gol 1.0. Mede estabilidade: quanto menor, mais consistente o padrão. Abaixo de 30% é muito estável; 30–50% moderado; acima de 50% indica alta dispersão e exige mais cautela."/></small><strong>{stats.cv_cost_goal_1?`${fmt(stats.cv_cost_goal_1,1)}%`:'—'}</strong></span><span><small>Custo do gol 2.0 <Tooltip text="Indicador equivalente para o segundo gol do jogo. Quanto menor, maior a recorrência histórica do comportamento relacionado ao segundo gol. Compare sempre com o CV 2.0."/></small><strong>{fmt(stats.cost_goal_2,2)}</strong></span><span><small>CV custo do gol 2.0 <Tooltip text="Coeficiente de variação do Custo do Gol 2.0. Quanto menor, mais previsível e estável o indicador. Valores elevados significam que a média do custo do segundo gol varia muito de jogo para jogo."/></small><strong>{stats.cv_cost_goal_2?`${fmt(stats.cv_cost_goal_2,1)}%`:'—'}</strong></span></div>{!stats.has_odds&&<div className="notice info">Sem odds conciliadas: os indicadores de custo do gol permanecem vazios.</div>}</div>
     <div className="panel pad odds-panel"><h3>Odds</h3><div className="numeric-stats odds-stats"><span><small>Odd média das vitórias</small><strong>{fmt(stats.avg_win_odd,2)}</strong></span><button className="odds-band-button" disabled={!stats.winning_odd_band} onClick={()=>setOddGamesOpen(true)}><small>Faixa de odds que mais vence</small><strong>{stats.winning_odd_band?.label||'—'}</strong>{stats.winning_odd_band&&<em>{stats.winning_odd_band.wins.toLocaleString('pt-BR')} vitórias · {fmt(stats.winning_odd_band.win_pct,1)}%</em>}<i>Ver jogos →</i></button><span><small>Maior odd vencedora</small><strong>{fmt(stats.max_win_odd,2)}</strong>{stats.max_win_odd_game&&<em>{stats.max_win_odd_game.opponent} · {stats.max_win_odd_game.score}{stats.max_win_odd_game.date?` · ${datePt(stats.max_win_odd_game.date)}`:''}</em>}</span><span><small>Odd média em jogos Over 2,5</small><strong>{fmt(stats.avg_odd_over_25,2)}</strong></span></div>{!stats.has_odds&&<div className="notice info">Importe e concilie as odds 1X2 para preencher esta seção.</div>}</div>
    </div>

    <div className="panel pad section-space descriptive-panel">
     <div className="panel-title"><div><h2>Estatística descritiva</h2><span>Consistência, dispersão e perfil de gols no recorte selecionado.</span></div></div>
     <div className="numeric-stats descriptive-stats">
      <span><small>Pontos por jogo <Tooltip text="Média de pontos por partida: vitória = 3, empate = 1 e derrota = 0. É uma medida simples de desempenho médio no recorte."/></small><strong>{fmt(stats.ppg,2)}</strong></span>
      <span><small>Mediana gols marcados <Tooltip text="Valor central dos gols marcados por jogo. É menos sensível a goleadas isoladas do que a média."/></small><strong>{fmt(stats.median_goals_for,2)}</strong></span>
      <span><small>Mediana gols sofridos <Tooltip text="Valor central dos gols sofridos por jogo. Ajuda a enxergar o padrão típico sem deixar goleadas distorcerem a leitura."/></small><strong>{fmt(stats.median_goals_against,2)}</strong></span>
      <span><small>DP gols marcados <Tooltip text="Desvio-padrão dos gols marcados. Quanto menor, mais regular é a produção ofensiva; quanto maior, mais oscilante."/></small><strong>{fmt(stats.std_goals_for,2)}</strong></span>
      <span><small>DP gols sofridos <Tooltip text="Desvio-padrão dos gols sofridos. Quanto menor, mais estável é o comportamento defensivo no recorte."/></small><strong>{fmt(stats.std_goals_against,2)}</strong></span>
      <span><small>CV gols marcados <Tooltip text="Coeficiente de variação dos gols marcados. Mede dispersão relativa à média. Valores menores indicam maior consistência ofensiva."/></small><strong>{stats.cv_goals_for==null?'—':`${fmt(stats.cv_goals_for,1)}%`}</strong></span>
      <span><small>CV gols sofridos <Tooltip text="Coeficiente de variação dos gols sofridos. Valores menores indicam um padrão defensivo mais estável."/></small><strong>{stats.cv_goals_against==null?'—':`${fmt(stats.cv_goals_against,1)}%`}</strong></span>
      <span><small>Clean sheets <Tooltip text="Percentual de jogos sem sofrer gol. É especialmente útil para avaliar Under, Ambas Não e força defensiva."/></small><strong>{fmt(stats.clean_sheet_pct,1)}%</strong></span>
      <span><small>Sem marcar <Tooltip text="Percentual de jogos em que o clube terminou sem fazer gol. Quanto maior, maior o risco para mercados de gols a favor."/></small><strong>{fmt(stats.failed_to_score_pct,1)}%</strong></span>
      <span><small>2+ gols marcados <Tooltip text="Percentual de jogos em que o clube marcou pelo menos dois gols. Ajuda a avaliar força ofensiva e linhas de Over."/></small><strong>{fmt(stats.scored_2_plus_pct,1)}%</strong></span>
      <span><small>2+ gols sofridos <Tooltip text="Percentual de jogos em que o clube sofreu pelo menos dois gols. Ajuda a identificar fragilidade defensiva e cenários de Over."/></small><strong>{fmt(stats.conceded_2_plus_pct,1)}%</strong></span>
      <span><small>Saldo médio <Tooltip text="Média da diferença entre gols marcados e sofridos por partida. Positivo indica superioridade média; negativo, inferioridade."/></small><strong>{fmt(stats.avg_goal_diff,2)}</strong></span>
     </div>
    </div>

    <div className="panel pad section-space descriptive-panel">
     <div className="panel-title"><div><h2>Relações estatísticas</h2><span>Quartis e associações bivariadas úteis para entender estabilidade e preço.</span></div></div>
     <div className="numeric-stats descriptive-stats">
      <span><small>Q1 / Q3 gols marcados <Tooltip text="Primeiro e terceiro quartis dos gols marcados. Metade dos jogos fica entre Q1 e Q3; é uma leitura robusta do intervalo típico de produção ofensiva."/></small><strong>{fmt(stats.q1_goals_for,2)} / {fmt(stats.q3_goals_for,2)}</strong></span>
      <span><small>IQR gols marcados <Tooltip text="Amplitude interquartil: Q3 menos Q1. Quanto menor, mais concentrada e estável é a produção ofensiva na metade central dos jogos."/></small><strong>{fmt(stats.iqr_goals_for,2)}</strong></span>
      <span><small>Q1 / Q3 gols sofridos <Tooltip text="Primeiro e terceiro quartis dos gols sofridos. Ajuda a enxergar o intervalo defensivo típico sem depender de goleadas fora da curva."/></small><strong>{fmt(stats.q1_goals_against,2)} / {fmt(stats.q3_goals_against,2)}</strong></span>
      <span><small>IQR gols sofridos <Tooltip text="Amplitude interquartil dos gols sofridos. Valores menores indicam maior concentração do comportamento defensivo."/></small><strong>{fmt(stats.iqr_goals_against,2)}</strong></span>
      <span><small>Correlação odd × pontos <Tooltip text="Correlação de Pearson entre a odd pré-jogo do clube e os pontos conquistados. Valor negativo indica que odds menores tendem a estar associadas a mais pontos; próximo de zero indica relação linear fraca."/></small><strong>{fmt(stats.corr_odd_points,2)}</strong></span>
      <span><small>Correlação odd × gols <Tooltip text="Correlação de Pearson entre a odd do clube e seus gols marcados. Valor negativo sugere que, quando o mercado precifica o clube como mais favorito, ele tende a marcar mais gols."/></small><strong>{fmt(stats.corr_odd_goals,2)}</strong></span>
      <span><small>Correlação gols marcados × sofridos <Tooltip text="Correlação de Pearson entre gols marcados e sofridos no mesmo jogo. Positiva pode indicar partidas mais abertas; negativa pode indicar jogos mais controlados quando o clube produz ofensivamente."/></small><strong>{fmt(stats.corr_goals_for_against,2)}</strong></span>
     </div>
    </div>

    {strengthLoading&&<div className="notice info section-space">Carregando comparação de forças...</div>}
    {strength&&<div className="panel pad section-space club-radar-section"><div className="panel-title"><div><h2>Força ofensiva e defensiva</h2><span>{strength.competition} · referência {strength.current_season}{strength.used_fallback_season?` (última temporada com jogos até ${strength.requested_season})`:''}</span></div><span>Defesa: quanto menor o índice, melhor.</span></div><RadarChart axes={radarAxes} labelA={selected.nome} labelB="Média dos demais clubes" note="1,00 representa a média da competição. A força defensiva mede gols concedidos relativos à liga: abaixo de 1,00 é melhor. No radar, os eixos defensivos são invertidos apenas visualmente para que uma área maior represente desempenho melhor; os números exibidos continuam sendo os índices originais."/></div>}

    <div className="blowout-grid section-space"><BlowoutTable title="10 maiores goleadas aplicadas" rows={stats.biggest_wins||[]}/><BlowoutTable title="10 maiores goleadas sofridas" rows={stats.biggest_losses||[]}/></div>

    <MarketValueEvolution data={marketEvolution} clubName={selected.nome}/>
   </>}

   {oddGamesOpen&&stats?.winning_odd_band&&<Modal title={`Vitórias na faixa ${stats.winning_odd_band.label}`} onClose={()=>setOddGamesOpen(false)}><div className="odds-band-summary"><strong>{stats.winning_odd_band.wins.toLocaleString('pt-BR')} vitórias</strong><span>{fmt(stats.winning_odd_band.win_pct,1)}% de aproveitamento em {stats.winning_odd_band.games.toLocaleString('pt-BR')} jogos dentro da faixa.</span></div><div className="table-scroll"><table><thead><tr><th>Data</th><th>Adversário</th><th>Placar</th><th>Odd</th><th>Mando</th><th>Competição</th><th>Temporada</th></tr></thead><tbody>{stats.winning_odd_band.games_detail.map((g:any,i:number)=><tr key={`${g.date}-${g.opponent}-${i}`}><td>{datePt(g.date)}</td><td><strong>{g.opponent}</strong></td><td>{g.score}</td><td><strong>{fmt(g.odd,2)}</strong></td><td>{g.venue==='home'?'Mandante':'Visitante'}</td><td>{g.competition||'—'}</td><td>{g.season||'—'}</td></tr>)}</tbody></table></div></Modal>}
  </>}
 </section>
}
