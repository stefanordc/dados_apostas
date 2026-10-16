import { useEffect, useState } from 'react'

type Theme = 'light' | 'dark'

const current = (): Theme => (document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light')

export default function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(current)
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    try { localStorage.setItem('theme', theme) } catch { /* armazenamento indisponível */ }
  }, [theme])
  const next = theme === 'dark' ? 'light' : 'dark'
  return (
    <button type="button" className="theme-toggle" onClick={() => setTheme(next)}
      aria-label={`Ativar tema ${next === 'dark' ? 'escuro' : 'claro'}`} title={`Tema ${next === 'dark' ? 'escuro' : 'claro'}`}>
      {theme === 'dark'
        ? <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>
        : <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>}
      <span>{theme === 'dark' ? 'Claro' : 'Escuro'}</span>
    </button>
  )
}
