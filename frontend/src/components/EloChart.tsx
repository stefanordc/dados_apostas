type Point = { elo: number; label?: string; data?: string | null }
type Props = { home: Point[]; away: Point[]; homeName: string; awayName: string }

type Coord = Point & { x: number; y: number }

const WIDTH = 1500
const HEIGHT = 310
const PAD_X = 48
const PAD_Y = 32

function coordsFor(
  points: Point[],
  min: number,
  max: number,
): Coord[] {
  if (!points.length) return []

  const range = Math.max(1, max - min)
  const usableWidth = WIDTH - PAD_X * 2
  const usableHeight = HEIGHT - PAD_Y * 2

  return points.map((p, i) => {
    const x =
      points.length === 1
        ? WIDTH / 2
        : PAD_X + (i / (points.length - 1)) * usableWidth

    const y =
      PAD_Y + usableHeight - ((p.elo - min) / range) * usableHeight

    return { ...p, x, y }
  })
}

function pathFor(coords: Coord[]) {
  return coords
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`)
    .join(' ')
}

function formatElo(value: number) {
  return new Intl.NumberFormat('pt-BR', {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  }).format(value)
}

export default function EloChart({
  home,
  away,
  homeName,
  awayName,
}: Props) {
  const all = [...home, ...away]

  if (!all.length) {
    return (
      <div className="empty-state compact">
        ELO ainda não disponível para este confronto.
      </div>
    )
  }

  const values = all.map(p => p.elo)
  const rawMin = Math.min(...values)
  const rawMax = Math.max(...values)
  const margin = Math.max(20, (rawMax - rawMin) * 0.08)

  const min = rawMin - margin
  const max = rawMax + margin

  const homeCoords = coordsFor(home, min, max)
  const awayCoords = coordsFor(away, min, max)

  const hp = pathFor(homeCoords)
  const ap = pathFor(awayCoords)

  return (
    <div className="elo-chart-wrap elo-chart-expanded">
      <div className="chart-legend">
        <span><i className="legend-home" />{homeName}</span>
        <span><i className="legend-away" />{awayName}</span>
      </div>

      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        preserveAspectRatio="none"
        role="img"
        aria-label="Evolução do ELO"
      >
        {[0, 1, 2, 3, 4].map(i => {
          const y = PAD_Y + ((HEIGHT - PAD_Y * 2) / 4) * i
          return (
            <line
              key={i}
              x1={PAD_X}
              x2={WIDTH - PAD_X}
              y1={y}
              y2={y}
              className="chart-grid"
            />
          )
        })}

        {hp && <path d={hp} className="chart-line home-line" />}
        {ap && <path d={ap} className="chart-line away-line" />}

        {homeCoords.map((p, i) => (
          <g key={`home-${i}`}>
            <circle cx={p.x} cy={p.y} r="3.4" className="elo-point home-point" />
            <text
              x={p.x}
              y={Math.max(15, p.y - 10)}
              textAnchor="middle"
              className="elo-data-label home-data-label"
            >
              {formatElo(p.elo)}
            </text>
          </g>
        ))}

        {awayCoords.map((p, i) => (
          <g key={`away-${i}`}>
            <circle cx={p.x} cy={p.y} r="3.4" className="elo-point away-point" />
            <text
              x={p.x}
              y={Math.min(HEIGHT - 5, p.y + 18)}
              textAnchor="middle"
              className="elo-data-label away-data-label"
            >
              {formatElo(p.elo)}
            </text>
          </g>
        ))}
      </svg>

      <div className="chart-scale chart-scale-expanded">
        <span>{Math.round(max).toLocaleString('pt-BR')}</span>
        <span>{Math.round(min).toLocaleString('pt-BR')}</span>
      </div>
    </div>
  )
}
