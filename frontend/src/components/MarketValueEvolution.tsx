type Row = {
  label: string
  temporada: string
  campeonato: string
  valor: number
  media_campeonato: number | null
  media_geral: number | null
  aproveitamento?: number | null
  jogos_aproveitamento?: number
  moeda: string
}

type Props = {
  data: {
    rows: Row[]
    currencies: string[]
    mixed_currencies: boolean
    comparison_rule?: string
  } | null
  clubName: string
}

const WIDTH = 1400
const HEIGHT = 300
const PAD_X = 72
const PAD_Y = 34

function money(value: number | null | undefined, currency: string) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—'
  return new Intl.NumberFormat('pt-BR', {
    style: 'currency',
    currency,
    notation: Math.abs(Number(value)) >= 1_000_000 ? 'compact' : 'standard',
    maximumFractionDigits: 1,
  }).format(Number(value))
}

function numberCompact(value: number) {
  return new Intl.NumberFormat('pt-BR', {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(value)
}

export default function MarketValueEvolution({ data, clubName }: Props) {
  const rows = data?.rows || []
  if (!rows.length) {
    return (
      <div className="panel pad section-space market-evolution-panel">
        <div className="panel-title"><h2>Evolução do valor de mercado</h2></div>
        <div className="empty-state compact">Ainda não há valores de mercado suficientes para este clube.</div>
      </div>
    )
  }

  const currencies = new Set(rows.map(r => r.moeda))
  const chartRows = currencies.size === 1 ? rows : rows.filter(r => r.moeda === rows[rows.length - 1].moeda)
  const currency = chartRows[0]?.moeda || 'EUR'
  const values = chartRows.flatMap(r => [r.valor, r.media_campeonato, r.media_geral]).filter((x): x is number => x !== null && x !== undefined && Number.isFinite(x))
  const minRaw = Math.min(...values)
  const maxRaw = Math.max(...values)
  const margin = Math.max(1, (maxRaw - minRaw) * 0.12)
  const min = Math.max(0, minRaw - margin)
  const max = maxRaw + margin
  const range = Math.max(1, max - min)
  const usableW = WIDTH - PAD_X * 2
  const usableH = HEIGHT - PAD_Y * 2

  const coords = (key: 'valor' | 'media_campeonato' | 'media_geral') => chartRows.map((r, i) => {
    const value = r[key]
    if (value === null || value === undefined) return null
    return {
      x: chartRows.length === 1 ? WIDTH / 2 : PAD_X + (i / (chartRows.length - 1)) * usableW,
      y: PAD_Y + usableH - ((Number(value) - min) / range) * usableH,
      value: Number(value),
      label: r.label,
    }
  }).filter(Boolean) as {x:number;y:number;value:number;label:string}[]

  const path = (pts: {x:number;y:number}[]) => pts.map((p, i) => `${i ? 'L' : 'M'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ')
  const club = coords('valor')
  const league = coords('media_campeonato')
  const overall = coords('media_geral')
  const performance = chartRows.map((r, i) => {
    const value = r.aproveitamento
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return null
    return {
      x: chartRows.length === 1 ? WIDTH / 2 : PAD_X + (i / (chartRows.length - 1)) * usableW,
      y: PAD_Y + usableH - (Math.max(0, Math.min(100, Number(value))) / 100) * usableH,
      value: Number(value),
      label: r.label,
    }
  }).filter(Boolean) as {x:number;y:number;value:number;label:string}[]

  return (
    <div className="panel pad section-space market-evolution-panel">
      <div className="panel-title market-evolution-title">
        <div>
          <h2>Evolução do valor de mercado</h2>
          <span>{clubName} × média do campeonato × média de todos os clubes cadastrados</span>
        </div>
        <span>{data?.comparison_rule}</span>
      </div>

      {data?.mixed_currencies && (
        <div className="notice info market-currency-note">
          Há valores em moedas diferentes. O gráfico exibe a moeda mais recente ({currency}); a tabela abaixo preserva todos os registros.
        </div>
      )}

      <div className="market-chart-legend">
        <span><i className="mv-club" />{clubName}</span>
        <span><i className="mv-league" />Média do campeonato</span>
        <span><i className="mv-global" />Média geral</span>
        <span><i className="mv-performance" />Aproveitamento</span>
      </div>

      <div className="market-chart-shell">
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} preserveAspectRatio="none" role="img" aria-label="Evolução do valor de mercado">
          {[0,1,2,3,4].map(i => {
            const y = PAD_Y + (usableH / 4) * i
            return <line key={i} x1={PAD_X} x2={WIDTH-PAD_X} y1={y} y2={y} className="market-grid-line" />
          })}
          <path d={path(club)} className="market-line market-line-club" />
          <path d={path(league)} className="market-line market-line-league" />
          <path d={path(overall)} className="market-line market-line-global" />
          {performance.length > 1 && <path d={path(performance)} className="market-line market-line-performance" />}

          {club.map((p, i) => <g key={`club-${i}`}><circle cx={p.x} cy={p.y} r="4" className="market-point market-point-club"/><text x={p.x} y={Math.max(16,p.y-11)} textAnchor="middle" className="market-data-label">{numberCompact(p.value)}</text></g>)}
          {league.map((p, i) => <circle key={`league-${i}`} cx={p.x} cy={p.y} r="3.2" className="market-point market-point-league"/>)}
          {overall.map((p, i) => <circle key={`global-${i}`} cx={p.x} cy={p.y} r="3.2" className="market-point market-point-global"/>)}
          {performance.map((p, i) => <g key={`performance-${i}`}><circle cx={p.x} cy={p.y} r="3.5" className="market-point market-point-performance"/><text x={p.x} y={Math.min(HEIGHT-12,p.y+17)} textAnchor="middle" className="market-performance-label">{p.value.toLocaleString('pt-BR',{minimumFractionDigits:1,maximumFractionDigits:1})}%</text></g>)}

          {chartRows.map((r, i) => {
            const x = chartRows.length === 1 ? WIDTH/2 : PAD_X + (i/(chartRows.length-1))*usableW
            return <text key={r.label+i} x={x} y={HEIGHT-5} textAnchor="middle" className="market-axis-label">{r.label}</text>
          })}
        </svg>
        <div className="market-y-scale"><span>{money(max,currency)}</span><span>{money(min,currency)}</span></div>
        <div className="market-performance-scale"><span>100%</span><span>0%</span></div>
      </div>

      <div className="table-scroll market-evolution-table-wrap">
        <table className="market-evolution-table">
          <thead><tr><th>Temporada</th><th>Campeonato</th><th>Clube</th><th>Média campeonato</th><th>Média geral</th><th>Aproveitamento</th><th>Moeda</th></tr></thead>
          <tbody>{rows.map((r, i)=><tr key={`${r.temporada}-${r.campeonato}-${i}`}><td>{r.temporada}</td><td>{r.campeonato}</td><td><strong>{money(r.valor,r.moeda)}</strong></td><td>{money(r.media_campeonato,r.moeda)}</td><td>{money(r.media_geral,r.moeda)}</td><td>{r.aproveitamento===null||r.aproveitamento===undefined?'—':`${r.aproveitamento.toLocaleString('pt-BR',{minimumFractionDigits:1,maximumFractionDigits:1})}%`}</td><td>{r.moeda}</td></tr>)}</tbody>
        </table>
      </div>
    </div>
  )
}
