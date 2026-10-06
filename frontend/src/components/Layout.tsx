import { NavLink, Outlet } from 'react-router-dom'

export default function Layout() {
  return (
    <div className="app-shell">
      <header className="global-header">
        <div className="brand"><img className="brand-logo" src="/elo-scout-logo.png" alt="ELO Scout" /><strong>ELO SCOUT</strong></div>
        <div className="global-search">Football Intelligence Platform</div>
        <div className="header-status"><span className="status-dot" /> Dados conectados</div>
      </header>
      <aside className="sidebar">
        <div className="sidebar-label">ANÁLISE</div>
        <nav>
          <NavLink to="/clubes">Clubes</NavLink>
          <NavLink to="/historico">Histórico de Jogos</NavLink>
          <NavLink to="/elo">ELO Clubes</NavLink>
          <NavLink to="/rankings">Rankings</NavLink>
          <NavLink to="/backtest">Backtest</NavLink>
        </nav>
        <div className="sidebar-label second">CONFIGURAÇÃO</div>
        <nav><NavLink to="/cadastros">Cadastros</NavLink></nav>
      </aside>
      <main className="workspace"><Outlet /></main>
    </div>
  )
}
