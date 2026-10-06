type RadarAxis = {
  label: string
  a: number | null | undefined
  b: number | null | undefined
  lowerBetter?: boolean
}

type Props = {
  title?: string
  axes: RadarAxis[]
  labelA: string
  labelB: string
  note?: string
}

const fmt = (value: number | null | undefined) =>
  value === null || value === undefined
    ? '—'
    : Number(value).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

export default function RadarChart({ title, axes, labelA, labelB, note }: Props) {
  const width = 520
  const height = 310
  const cx = 260
  const cy = 148
  const radius = 98
  const clean = axes.length >= 3 ? axes : [
    ...axes,
    ...axes.map(x => ({ ...x, label: `${x.label} · comparação` })),
  ]
  const plotValue = (axis: RadarAxis, key: 'a' | 'b') => {
    const raw = axis[key]
    if (raw === null || raw === undefined || !Number.isFinite(raw)) return 0
    if (axis.lowerBetter && raw > 0) return 1 / raw
    return raw
  }
  const allValues = clean.flatMap(x => [plotValue(x, 'a'), plotValue(x, 'b')]).filter(v => Number.isFinite(v))
  const maxValue = Math.max(1.5, ...(allValues.length ? allValues : [1.5])) * 1.12

  const point = (index: number, value: number) => {
    const angle = -Math.PI / 2 + (index * Math.PI * 2) / clean.length
    const r = radius * Math.max(0, Math.min(1, value / maxValue))
    return [cx + Math.cos(angle) * r, cy + Math.sin(angle) * r]
  }

  const axisPoint = (index: number, r = radius) => {
    const angle = -Math.PI / 2 + (index * Math.PI * 2) / clean.length
    return [cx + Math.cos(angle) * r, cy + Math.sin(angle) * r]
  }

  const polygon = (key: 'a' | 'b') => clean
    .map((axis, i) => point(i, plotValue(axis, key)).join(','))
    .join(' ')

  const ring = (factor: number) => clean
    .map((_, i) => axisPoint(i, radius * factor).join(','))
    .join(' ')

  return (
    <div className="radar-card">
      {title && <div className="radar-title"><h3>{title}</h3></div>}
      <div className="radar-legend">
        <span><i className="radar-a" />{labelA}</span>
        <span><i className="radar-b" />{labelB}</span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={title || 'Gráfico aranha'}>
        {[0.25, 0.5, 0.75, 1].map(f => <polygon key={f} points={ring(f)} className="radar-ring" />)}
        {clean.map((axis, i) => {
          const [x, y] = axisPoint(i)
          const [lx, ly] = axisPoint(i, radius + 28)
          return <g key={`${axis.label}-${i}`}>
            <line x1={cx} y1={cy} x2={x} y2={y} className="radar-axis" />
            <text x={lx} y={ly} className="radar-label" textAnchor={lx < cx - 10 ? 'end' : lx > cx + 10 ? 'start' : 'middle'}>
              {axis.label}
            </text>
            <text x={lx} y={ly + 13} className="radar-values" textAnchor={lx < cx - 10 ? 'end' : lx > cx + 10 ? 'start' : 'middle'}>
              {fmt(axis.a)} / {fmt(axis.b)}
            </text>
          </g>
        })}
        <polygon points={polygon('a')} className="radar-polygon radar-polygon-a" />
        <polygon points={polygon('b')} className="radar-polygon radar-polygon-b" />
        {clean.map((axis, i) => {
          const [ax, ay] = point(i, plotValue(axis, 'a'))
          const [bx, by] = point(i, plotValue(axis, 'b'))
          return <g key={`points-${i}`}>
            <circle cx={ax} cy={ay} r="3.2" className="radar-point-a" />
            <circle cx={bx} cy={by} r="3.2" className="radar-point-b" />
          </g>
        })}
      </svg>
      {note && <p className="radar-note">{note}</p>}
    </div>
  )
}
