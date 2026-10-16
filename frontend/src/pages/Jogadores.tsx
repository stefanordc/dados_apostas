import { useEffect, useMemo, useState } from 'react'
import { api, query } from '../api'
import Autocomplete from '../components/Autocomplete'


type Player = {
  player_id:string
  nome:string
  aliases:string[]
  foto_url?:string|null
  posicao?:string|null
  posicoes:string[]
  nacionalidade?:string|null
  nacionalidades:string[]
  clube?:string|null
  clubes:string[]
  temporadas:string[]
  tabelas:string[]
}
type FilterOptions={positions:string[];nationalities:string[];clubs:string[];seasons:string[];tables:{key:string;label:string;available:boolean}[]}
type DirectoryResponse={rows:Player[];total:number;page:number;page_size:number;pages:number}

const fmt=(v:any,d=0)=>v===null||v===undefined?'—':Number(v).toLocaleString('pt-BR',{minimumFractionDigits:d,maximumFractionDigits:d})
const aliasesTitle=(p:Player)=>p.aliases?.length>1?`Outros nomes cadastrados: ${p.aliases.filter(x=>x!==p.nome).join(' · ')}`:'Nome único cadastrado'
const headerLabel=(value:string)=>value.replace(/_/g,' ').replace(/\b\w/g,(m:string)=>m.toUpperCase())

function PlayerPhoto({player,large=false}:{player:Player;large?:boolean}){
 const[broken,setBroken]=useState(false)
 if(!player.foto_url||broken)return <span className={`player-photo-placeholder ${large?'large':''}`}>{player.nome?.[0]||'?'}</span>
 return <img className={large?'player-photo-large':'player-photo'} src={player.foto_url} alt={player.nome} onError={()=>setBroken(true)}/>
}

function RawTable({rows}:{rows:any[]}){
 if(!rows?.length)return <div className="empty-state compact">Nenhum registro neste recorte.</div>
 const columns=Array.from(new Set(rows.flatMap(r=>Object.keys(r))))
 return <div className="table-scroll player-raw-scroll"><table className="player-raw-table"><thead><tr>{columns.map(c=><th key={c}>{headerLabel(c)}</th>)}</tr></thead><tbody>{rows.map((r,i)=><tr key={i}>{columns.map(c=><td key={c}>{r[c]===null||r[c]===undefined?'—':typeof r[c]==='object'?JSON.stringify(r[c]):String(r[c])}</td>)}</tr>)}</tbody></table></div>
}

export default function Jogadores(){
 const[options,setOptions]=useState<FilterOptions>({positions:[],nationalities:[],clubs:[],seasons:[],tables:[]})
 const[search,setSearch]=useState('')
 const[position,setPosition]=useState('')
 const[nationality,setNationality]=useState('')
 const[club,setClub]=useState('')
 const[data,setData]=useState<DirectoryResponse>({rows:[],total:0,page:1,page_size:60,pages:1})
 const[page,setPage]=useState(1)
 const[loading,setLoading]=useState(false)
 const[selected,setSelected]=useState<Player|null>(null)
 const[profile,setProfile]=useState<any>(null)
 const[profileLoading,setProfileLoading]=useState(false)
 const[profileSeason,setProfileSeason]=useState('')
 const[profileClub,setProfileClub]=useState('')

 useEffect(()=>{api<FilterOptions>('/api/player-directory/filters').then(setOptions)},[])
 useEffect(()=>{setPage(1)},[search,position,nationality,club])
 useEffect(()=>{
   let active=true
   const timer=setTimeout(()=>{
     setLoading(true)
     api<DirectoryResponse>(`/api/player-directory?${query({q:search||undefined,position:position||undefined,nationality:nationality||undefined,club:club||undefined,page,page_size:60})}`)
       .then(d=>{if(active)setData(d)})
       .finally(()=>{if(active)setLoading(false)})
   },180)
   return()=>{active=false;clearTimeout(timer)}
 },[search,position,nationality,club,page])

 useEffect(()=>{
   if(!selected){setProfile(null);return}
   setProfileLoading(true)
   api<any>(`/api/player-directory/${encodeURIComponent(selected.player_id)}/profile?${query({season:profileSeason||undefined,club:profileClub||undefined})}`)
     .then(setProfile)
     .finally(()=>setProfileLoading(false))
 },[selected?.player_id,profileSeason,profileClub])

 function choosePlayer(p:Player){
   setSelected(p);setProfile(null);setProfileSeason('');setProfileClub('')
 }

 const unavailable=useMemo(()=>options.tables.filter(x=>!x.available).map(x=>x.label),[options.tables])

 return <section className="page players-page">
  <div className="page-header"><div><span className="eyebrow">PLAYER DATABASE</span><h1>Jogadores</h1><p>Perfil consolidado usando o ID do jogador em todas as bases individuais.</p></div></div>

  {!selected?<>
   <div className="panel player-filter-grid">
    <div className="field"><label>Jogador</label><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Buscar jogador..."/></div>
    <Autocomplete label="Posição" value={position} options={options.positions} onChange={setPosition} placeholder="Todas as posições"/>
    <Autocomplete label="Nacionalidade" value={nationality} options={options.nationalities} onChange={setNationality} placeholder="Todas as nacionalidades"/>
    <Autocomplete label="Clube" value={club} options={options.clubs} onChange={setClub} placeholder="Todos os clubes"/>
    <button className="secondary" onClick={()=>{setSearch('');setPosition('');setNationality('');setClub('')}}>Limpar filtros</button>
   </div>
   {unavailable.length>0&&<div className="notice info">Tabelas ainda não detectadas: {unavailable.join(', ')}. As demais informações continuam disponíveis.</div>}
   {loading?<div className="empty-state">Carregando jogadores...</div>:<>
    <div className="player-directory">{data.rows.map(p=><button key={p.player_id} className="player-card" onClick={()=>choosePlayer(p)}>
     <PlayerPhoto player={p}/><div><strong title={aliasesTitle(p)}>{p.nome}</strong><span>{p.posicao||'Posição não informada'}</span><small>{p.nacionalidade||'Nacionalidade não informada'}{p.clube?` · ${p.clube}`:''}</small></div>
    </button>)}</div>
    {!data.rows.length&&<div className="empty-state">Nenhum jogador encontrado.</div>}
    <div className="directory-pagination"><span>{data.total.toLocaleString('pt-BR')} jogadores · página {data.page} de {data.pages}</span><div><button className="secondary" disabled={data.page<=1} onClick={()=>setPage(p=>Math.max(1,p-1))}>← Anterior</button><button className="secondary" disabled={data.page>=data.pages} onClick={()=>setPage(p=>p+1)}>Próxima →</button></div></div>
   </>}
  </>:<>
   <button className="back-link" onClick={()=>{setSelected(null);setProfile(null)}}>← Voltar aos jogadores</button>
   <div className="panel player-profile-head">
    <div className="player-profile-identity"><PlayerPhoto player={selected} large/><div><span className="eyebrow">PLAYER PROFILE</span><h2 title={aliasesTitle(selected)}>{selected.nome}</h2><p>{selected.posicao||'Posição não informada'} · {selected.nacionalidade||'Nacionalidade não informada'}{selected.clube?` · ${selected.clube}`:''}</p>{selected.aliases.length>1&&<small>Também cadastrado como: {selected.aliases.filter(x=>x!==selected.nome).join(' · ')}</small>}</div></div>
    {profile&&<div className="player-head-kpis"><span><small>Gols</small><strong>{fmt(profile.totals.gols_marcados)}</strong></span><span><small>Assistências</small><strong>{fmt(profile.totals.assistencias)}</strong></span><span><small>Minutos</small><strong>{fmt(profile.totals.minutos)}</strong></span></div>}
   </div>

   <div className="panel player-profile-filters">
    <div className="field"><label>Temporada</label><select value={profileSeason} onChange={e=>setProfileSeason(e.target.value)}><option value="">Todas</option>{(profile?.filters?.seasons||selected.temporadas||[]).map((s:string)=><option key={s}>{s}</option>)}</select></div>
    <Autocomplete label="Clube" value={profileClub} options={profile?.filters?.clubs||selected.clubes||[]} onChange={setProfileClub} placeholder="Todos os clubes"/>
    <button className="secondary" onClick={()=>{setProfileSeason('');setProfileClub('')}}>Limpar filtros</button>
   </div>

   {profileLoading&&<div className="notice info">Atualizando perfil do jogador...</div>}
   {profile&&<>
    <div className="player-summary-grid">
     <div className="panel pad"><h3>Produção</h3><div className="numeric-stats player-numeric-stats"><span><small>Gols marcados</small><strong>{fmt(profile.totals.gols_marcados)}</strong></span><span><small>Assistências</small><strong>{fmt(profile.totals.assistencias)}</strong></span><span><small>Participações em gols</small><strong>{fmt(profile.derived.goals_assists)}</strong></span><span><small>Hat-tricks</small><strong>{fmt(profile.totals.hat_tricks)}</strong></span></div></div>
     <div className="panel pad"><h3>Tempo e eficiência</h3><div className="numeric-stats player-numeric-stats"><span><small>Minutos</small><strong>{fmt(profile.totals.minutos)}</strong></span><span><small>Gols / 90</small><strong>{fmt(profile.derived.goals_per90,2)}</strong></span><span><small>Assistências / 90</small><strong>{fmt(profile.derived.assists_per90,2)}</strong></span><span><small>G+A / 90</small><strong>{fmt(profile.derived.goal_contributions_per90,2)}</strong></span></div></div>
     <div className="panel pad"><h3>Defesa e disciplina</h3><div className="numeric-stats player-numeric-stats"><span><small>Gols sofridos</small><strong>{fmt(profile.totals.gols_sofridos)}</strong></span><span><small>Gols sofridos / 90</small><strong>{fmt(profile.derived.conceded_per90,2)}</strong></span><span><small>Disciplina</small><strong>{fmt(profile.totals.disciplina)}</strong></span><span><small>Disciplina / 90</small><strong>{fmt(profile.derived.discipline_per90,2)}</strong></span></div></div>
    </div>

    <div className="panel pad section-space">
     <div className="panel-title"><div><h2>Evolução por temporada</h2><span>Somas feitas pelo ID do jogador, mesmo quando o nome varia entre as bases.</span></div></div>
     <div className="table-scroll"><table className="player-season-table"><thead><tr><th>Temporada</th><th>Assistências</th><th>Minutos</th><th>Gols Marcados</th><th>Gols Sofridos</th><th>Disciplina</th><th>Hat-tricks</th></tr></thead><tbody>{profile.by_season?.length?profile.by_season.map((r:any)=><tr key={r.temporada}><td><strong>{r.temporada}</strong></td><td>{fmt(r.assistencias)}</td><td>{fmt(r.minutos)}</td><td>{fmt(r.gols_marcados)}</td><td>{fmt(r.gols_sofridos)}</td><td>{fmt(r.disciplina)}</td><td>{fmt(r.hat_tricks)}</td></tr>):<tr><td colSpan={7} className="empty-row">Sem temporadas identificáveis nas tabelas.</td></tr>}</tbody></table></div>
    </div>

    <div className="player-source-grid section-space">{profile.sources.map((source:any)=><div className="panel pad player-source-card" key={source.key}>
     <div className="panel-title"><div><h2>{source.label}</h2><span>{source.table}</span></div><strong>{fmt(source.total)}</strong></div>
     {Object.keys(source.extras||{}).length>0&&<div className="numeric-stats source-extras">{Object.entries(source.extras).map(([k,v])=><span key={k}><small>{headerLabel(k)}</small><strong>{fmt(v)}</strong></span>)}</div>}
     <details><summary>Ver todos os dados encontrados ({source.rows.length.toLocaleString('pt-BR')} registros)</summary><RawTable rows={source.rows}/></details>
    </div>)}</div>
   </>}
  </>}
 </section>
}
