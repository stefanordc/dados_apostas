import { ReactNode, useEffect, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import ThemeToggle from './ThemeToggle'

const svg=(children:ReactNode)=><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>

const ICONS:Record<string,ReactNode>={
 clubes:svg(<><path d="M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6z"/><path d="M9 12l2 2 4-4"/></>),
 jogadores:svg(<><circle cx="12" cy="8" r="3.5"/><path d="M5 20c0-3.6 3.1-6 7-6s7 2.4 7 6"/></>),
 historico:svg(<><path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v4h4"/><path d="M12 7v5l3 2"/></>),
 elo:svg(<><path d="M4 20V10M10 20V4M16 20v-8M22 20H2"/></>),
 rankings:svg(<><path d="M8 21h8M12 17v4"/><path d="M7 4h10v5a5 5 0 0 1-10 0z"/><path d="M7 6H4v2a3 3 0 0 0 3 3M17 6h3v2a3 3 0 0 1-3 3"/></>),
 individual:svg(<><circle cx="12" cy="9" r="4"/><path d="M8.5 13.5L7 21l5-3 5 3-1.5-7.5"/></>),
 estatisticas:svg(<><path d="M3 3v18h18"/><path d="M7 15l4-5 3 3 5-7"/></>),
 scanner:svg(<><circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/><path d="M8.5 11h5"/></>),
 backtesting:svg(<><path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v4h4"/><path d="M9 14l2.5-3 2 2L17 9"/></>),
 bet:svg(<><circle cx="12" cy="12" r="9"/><path d="M12 7v10M9.5 9.5C9.5 8.4 10.6 8 12 8s2.5.6 2.5 1.8c0 2.4-5 1.4-5 4 0 1.1 1.1 1.9 2.5 1.9s2.5-.5 2.5-1.7"/></>),
 cadastros:svg(<><path d="M4 6h16M4 12h16M4 18h10"/><circle cx="19" cy="18" r="2"/></>),
}

type Item={to:string;label:string;icon:string}
const ANALYSIS:Item[]=[
 {to:'/clubes',label:'Clubes',icon:'clubes'},{to:'/jogadores',label:'Jogadores',icon:'jogadores'},
 {to:'/historico',label:'Histórico de Jogos',icon:'historico'},{to:'/elo',label:'ELO Clubes',icon:'elo'},
 {to:'/rankings',label:'Rankings',icon:'rankings'},{to:'/ranking-individual',label:'Ranking Individual',icon:'individual'},
 {to:'/estatisticas',label:'Estatísticas',icon:'estatisticas'},{to:'/scanner',label:'Scanner',icon:'scanner'},
 {to:'/backtesting',label:'Backtesting',icon:'backtesting'},{to:'/bet-teste',label:'BET Teste',icon:'bet'}]
const CONFIG:Item[]=[{to:'/cadastros',label:'Cadastros',icon:'cadastros'}]

const STORAGE_KEY='sidebar-collapsed'
const initial=()=>{try{return localStorage.getItem(STORAGE_KEY)==='1'}catch{return false}}

export default function Layout() {
  const [collapsed,setCollapsed]=useState<boolean>(initial)
  useEffect(()=>{try{localStorage.setItem(STORAGE_KEY,collapsed?'1':'0')}catch{/* armazenamento indisponível */}},[collapsed])
  const link=(item:Item)=>
    <NavLink key={item.to} to={item.to} title={collapsed?item.label:undefined} aria-label={item.label}>
      <span className="nav-icon">{ICONS[item.icon]}</span><span className="nav-text">{item.label}</span>
    </NavLink>
  return (
    <div className={`app-shell${collapsed?' collapsed':''}`}>
      <header className="global-header">
        <button type="button" className="sidebar-toggle" onClick={()=>setCollapsed(c=>!c)} aria-expanded={!collapsed}
          aria-label={collapsed?'Expandir menu lateral':'Recolher menu lateral'} title={collapsed?'Expandir menu':'Recolher menu'}>
          {svg(collapsed?<path d="M4 6h16M4 12h16M4 18h16"/>:<><path d="M4 6h16M4 12h10M4 18h16"/><path d="M18 9l-3 3 3 3"/></>)}
        </button>
        <div className="brand"><img className="brand-logo" src="/elo-scout-logo.png" alt="ELO Scout" /><strong>ELO SCOUT</strong></div>
        <div className="global-search">Football Intelligence Platform</div>
        <div className="header-status"><span className="status-dot" /> Dados conectados</div>
        <ThemeToggle />
      </header>
      <aside className="sidebar">
        <div className="sidebar-label">ANÁLISE</div>
        <nav>{ANALYSIS.map(link)}</nav>
        <div className="sidebar-label second">CONFIGURAÇÃO</div>
        <nav>{CONFIG.map(link)}</nav>
      </aside>
      <main className="workspace"><Outlet /></main>
    </div>
  )
}
