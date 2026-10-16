import { useEffect, useMemo, useState } from 'react'
import { api, query } from '../api'
import Autocomplete from '../components/Autocomplete'

type Filters={positions:string[];nationalities:string[];clubs:string[];seasons:string[];tables:{key:string;label:string;available:boolean}[]}
type Metric='assistencias'|'minutos'|'gols_marcados'|'gols_sofridos'|'disciplina'|'dobletes'|'hat_tricks'|'poker_tricks'|'cinco_mais_gols'
type SortKey='rank'|'name'|'position'|'nationality'|'club'|'value'
const TABS:{key:Metric;label:string}[]=[
 {key:'assistencias',label:'Assistências'},
 {key:'minutos',label:'Minutos'},
 {key:'gols_marcados',label:'Gols Marcados'},
 {key:'gols_sofridos',label:'Gols Sofridos'},
 {key:'disciplina',label:'Disciplina'},
 {key:'dobletes',label:'Dobletes'},
 {key:'hat_tricks',label:'Hat-Tricks'},
 {key:'poker_tricks',label:'Poker Tricks'},
 {key:'cinco_mais_gols',label:'5 ou mais gols'},
]
const fmt=(v:any,d=0)=>v===null||v===undefined?'—':Number(v).toLocaleString('pt-BR',{minimumFractionDigits:d,maximumFractionDigits:d})

export default function RankingIndividual(){
 const[filters,setFilters]=useState<Filters>({positions:[],nationalities:[],clubs:[],seasons:[],tables:[]})
 const[metric,setMetric]=useState<Metric>('assistencias')
 const[season,setSeason]=useState('all')
 const[club,setClub]=useState('')
 const[position,setPosition]=useState('')
 const[nationality,setNationality]=useState('')
 const[data,setData]=useState<any>({rows:[],label:'Assistências',source_available:true})
 const[loading,setLoading]=useState(false)
 const[sortKey,setSortKey]=useState<SortKey>('value')
 const[sortDir,setSortDir]=useState<'asc'|'desc'>('desc')

 useEffect(()=>{api<Filters>('/api/player-rankings/filters').then(setFilters)},[])
 useEffect(()=>{
   let active=true;setLoading(true)
   api<any>(`/api/player-rankings?${query({metric,season:season==='all'?undefined:season,club:club||undefined,position:position||undefined,nationality:nationality||undefined})}`)
    .then(d=>{if(active)setData(d)})
    .finally(()=>{if(active)setLoading(false)})
   return()=>{active=false}
 },[metric,season,club,position,nationality])
 useEffect(()=>{setSortKey('value');setSortDir('desc')},[metric])

 function sort(key:SortKey){if(sortKey===key)setSortDir(d=>d==='desc'?'asc':'desc');else{setSortKey(key);setSortDir(key==='name'||key==='position'||key==='nationality'||key==='club'?'asc':'desc')}}
 const rows=useMemo(()=>{
   const d=sortDir==='asc'?1:-1
   return [...(data.rows||[])].sort((a:any,b:any)=>{
    const map:any={rank:'posicao_ranking',name:'nome',position:'posicao',nationality:'nacionalidade',club:'clube',value:'valor'}
    const av=a[map[sortKey]],bv=b[map[sortKey]]
    if(typeof av==='string'||typeof bv==='string')return String(av||'').localeCompare(String(bv||''),'pt-BR',{sensitivity:'base',numeric:true})*d
    return ((Number(av)||0)-(Number(bv)||0))*d
   })
 },[data.rows,sortKey,sortDir])
 function H({k,label}:{k:SortKey;label:string}){return <th className="sortable-ranking-th"><button onClick={()=>sort(k)}>{label}<span className="ranking-sort-icon">{sortKey===k?(sortDir==='desc'?'▼':'▲'):'↕'}</span></button></th>}

 return <section className="page individual-ranking-page">
  <div className="page-header"><div><span className="eyebrow">PLAYER INTELLIGENCE</span><h1>Ranking Individual</h1><p>Rankings consolidados pelo ID do jogador, somando todas as linhas válidas do recorte.</p></div></div>
  <div className="panel individual-ranking-filters">
   <div className="field"><label>Temporada</label><select value={season} onChange={e=>setSeason(e.target.value)}><option value="all">Todas as temporadas</option>{filters.seasons.map(s=><option key={s}>{s}</option>)}</select></div>
   <Autocomplete label="Clube" value={club} options={filters.clubs} onChange={setClub} placeholder="Todos os clubes"/>
   <Autocomplete label="Posição" value={position} options={filters.positions} onChange={setPosition} placeholder="Todas as posições"/>
   <Autocomplete label="Nacionalidade" value={nationality} options={filters.nationalities} onChange={setNationality} placeholder="Todas as nacionalidades"/>
   <button className="secondary" onClick={()=>{setSeason('all');setClub('');setPosition('');setNationality('')}}>Limpar filtros</button>
  </div>
  <div className="rankings-tabs player-ranking-tabs">{TABS.map(t=><button key={t.key} className={metric===t.key?'active':''} onClick={()=>setMetric(t.key)}>{t.label}</button>)}</div>
  <div className="panel rankings-panel">
   <div className="panel-title"><div><h2>{data.label}</h2><span>{rows.length.toLocaleString('pt-BR')} jogadores no recorte · soma por ID</span></div>{metric==='disciplina'&&<span>Maior = mais ocorrências disciplinares</span>}</div>
   {!data.source_available&&<div className="notice info">A tabela deste ranking ainda não foi detectada no banco.</div>}
   {loading?<div className="empty-state">Calculando ranking individual...</div>:rows.length?<div className="table-scroll"><table className="rankings-table player-ranking-table"><thead><tr><H k="rank" label="#"/><H k="name" label="Jogador"/><H k="position" label="Posição"/><H k="nationality" label="Nacionalidade"/><H k="club" label="Clube"/><H k="value" label={data.label}/></tr></thead><tbody>{rows.map((r:any,i:number)=><tr key={r.player_id}><td><span className={`rank-position ${i<3?'top':''}`}>{i+1}</span></td><td><div className="player-ranking-name">{r.foto_url?<img src={r.foto_url} alt=""/>:<span className="mini-player">{String(r.nome||'?')[0]}</span>}<strong title={r.aliases?.length>1?`Outros nomes: ${r.aliases.filter((x:string)=>x!==r.nome).join(' · ')}`:'Nome único cadastrado'}>{r.nome}</strong></div></td><td>{r.posicao||'—'}</td><td>{r.nacionalidade||'—'}</td><td>{r.clube||'—'}</td><td><strong className="ranking-main-value">{fmt(r.valor)}</strong></td></tr>)}</tbody></table></div>:<div className="empty-state">Nenhum jogador com dados neste recorte.</div>}
  </div>
 </section>
}
