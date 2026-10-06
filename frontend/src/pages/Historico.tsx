import { useEffect, useMemo, useState } from 'react'
import { api, query } from '../api'
import Autocomplete from '../components/Autocomplete'
import type { HistoryOptions, HistoryStats } from '../types'

const emptyOptions: HistoryOptions = { countries: [], seasons: [], competitions: [], rounds: [], clubs: [], home_teams: [], away_teams: [], winners: [] }
type Filters = { country:string;season:string;competition:string;round:string;club:string;home:string;away:string;winner:string;home_goals_min:string;home_goals_max:string;away_goals_min:string;away_goals_max:string;goal_diff_min:string;goal_diff_max:string;home_win:string;away_win:string }
const initialFilters: Filters = { country:'',season:'',competition:'',round:'',club:'',home:'',away:'',winner:'',home_goals_min:'',home_goals_max:'',away_goals_min:'',away_goals_max:'',goal_diff_min:'',goal_diff_max:'',home_win:'',away_win:'' }
const int = (v:number) => Number(v||0).toLocaleString('pt-BR')
const dec = (v:number) => Number(v||0).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2})

export default function Historico(){
 const [filters,setFilters]=useState(initialFilters);const [options,setOptions]=useState(emptyOptions);const [stats,setStats]=useState<HistoryStats|null>(null);const [rows,setRows]=useState<Record<string,unknown>[]>([]);const [total,setTotal]=useState(0);const [page,setPage]=useState(1);const [loading,setLoading]=useState(false)
 const params=useMemo(()=>{const p:Record<string,string>={};Object.entries(filters).forEach(([k,v])=>{if(v!=='')p[k]=v});return p},[filters])
 useEffect(()=>{const t=setTimeout(()=>api<HistoryOptions>(`/api/history/options?${query(params)}`).then(setOptions).catch(console.error),120);return()=>clearTimeout(t)},[params])
 useEffect(()=>setPage(1),[params])
 useEffect(()=>{setLoading(true);api<any>(`/api/history/games?${query({...params,page,page_size:50})}`).then(d=>{setStats(d.stats);setRows(d.rows);setTotal(d.total)}).finally(()=>setLoading(false))},[params,page])
 function set<K extends keyof Filters>(k:K,v:Filters[K]){setFilters(p=>({...p,[k]:v}))}
 const cards=stats?[
  ['Total de Jogos',int(stats.total_jogos)],['Vitórias Casa',int(stats.vitorias_casa)],['Vitórias Fora',int(stats.vitorias_fora)],
  ['% Vitórias Casa',`${dec(stats.percentual_vitorias_casa)}%`],['% Empates',`${dec((stats as any).percentual_empates||0)}%`],['% Vitórias Fora',`${dec(stats.percentual_vitorias_fora)}%`],
  ['Gols Marcados Casa',int(stats.gols_casa)],['Gols Marcados Fora',int(stats.gols_fora)],['Total de Gols',int(stats.total_gols)],
  ['Média de Gols Casa',dec(stats.media_gols_casa)],['Média de Gols Fora',dec(stats.media_gols_fora)],['Média Geral de Gols',dec(stats.media_geral_gols)]
 ]:[]
 return <section className="page">
  <div className="page-header"><div><span className="eyebrow">DATABASE</span><h1>Histórico de Jogos</h1><p>Consulta dinâmica da base histórica.</p></div><button className="secondary" onClick={()=>setFilters(initialFilters)}>Limpar filtros</button></div>
  <div className="panel filters-grid">
   <Autocomplete label="País" value={filters.country} options={options.countries} onChange={v=>set('country',v)}/><Autocomplete label="Temporada" value={filters.season} options={options.seasons} onChange={v=>set('season',v)}/><Autocomplete label="Campeonato" value={filters.competition} options={options.competitions} onChange={v=>set('competition',v)}/><Autocomplete label="Fase / Rodada" value={filters.round} options={options.rounds} onChange={v=>set('round',v)}/>
   <Autocomplete label="Clube" value={filters.club} options={options.clubs} onChange={v=>set('club',v)}/><Autocomplete label="Mandante" value={filters.home} options={options.home_teams} onChange={v=>set('home',v)}/><Autocomplete label="Visitante" value={filters.away} options={options.away_teams} onChange={v=>set('away',v)}/><Autocomplete label="Vencedor" value={filters.winner} options={options.winners} onChange={v=>set('winner',v)}/>
   <div className="range-field"><label>Gols Casa</label><div><input type="number" min="0" placeholder="Mín." value={filters.home_goals_min} onChange={e=>set('home_goals_min',e.target.value)}/><input type="number" min="0" placeholder="Máx." value={filters.home_goals_max} onChange={e=>set('home_goals_max',e.target.value)}/></div></div>
   <div className="range-field"><label>Gols Fora</label><div><input type="number" min="0" placeholder="Mín." value={filters.away_goals_min} onChange={e=>set('away_goals_min',e.target.value)}/><input type="number" min="0" placeholder="Máx." value={filters.away_goals_max} onChange={e=>set('away_goals_max',e.target.value)}/></div></div>
   <div className="range-field"><label>Saldo de Gols</label><div><input type="number" min="0" placeholder="Mín." value={filters.goal_diff_min} onChange={e=>set('goal_diff_min',e.target.value)}/><input type="number" min="0" placeholder="Máx." value={filters.goal_diff_max} onChange={e=>set('goal_diff_max',e.target.value)}/></div></div>
   <div className="field"><label>Vencedor Casa</label><select value={filters.home_win} onChange={e=>set('home_win',e.target.value)}><option value="">Todos</option><option value="sim">Sim</option><option value="nao">Não</option></select></div>
   <div className="field"><label>Vencedor Fora</label><select value={filters.away_win} onChange={e=>set('away_win',e.target.value)}><option value="">Todos</option><option value="sim">Sim</option><option value="nao">Não</option></select></div>
  </div>
  <div className="cards history-cards">{cards.map(([l,v])=><div className="metric-card" key={String(l)}><span>{l}</span><strong>{v}</strong></div>)}</div>
  <div className="panel table-panel"><div className="table-toolbar"><span>{loading?'Carregando...':`${int(total)} jogos encontrados`}</span><div><button disabled={page<=1} onClick={()=>setPage(p=>p-1)}>Anterior</button><span>Página {page}</span><button disabled={page*50>=total} onClick={()=>setPage(p=>p+1)}>Próxima</button></div></div>
   <div className="table-scroll"><table><thead><tr><th>Data</th><th>País</th><th>Temporada</th><th>Campeonato</th><th>Fase</th><th>Mandante</th><th>GC</th><th>GF</th><th>Visitante</th><th>Saldo</th><th>Vencedor</th></tr></thead><tbody>{rows.map((r,i)=><tr key={String(r.id??i)}><td>{String(r.data??'')}</td><td>{String(r.pais??'')}</td><td>{String(r.temporada??'')}</td><td>{String(r.campeonato??'')}</td><td>{String(r.rodada??'')}</td><td>{String(r.casa??'')}</td><td>{String(r.gols_casa??'')}</td><td>{String(r.gols_fora??'')}</td><td>{String(r.fora??'')}</td><td>{String(r.saldo_gols??'')}</td><td>{String(r.vencedor??'')}</td></tr>)}</tbody></table></div>
  </div>
 </section>
}
