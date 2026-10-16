type Market = { probability: number; percent: number; odds: number | null }
type Props = { data: any; homeName: string; awayName: string }

const odd = (m?: Market) => m?.odds == null ? '—' : Number(m.odds).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const pct = (m?: Market) => m?.percent == null ? '—' : `${Number(m.percent).toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`

export default function PoissonBoard({ data, homeName, awayName }: Props) {
  if (!data) return null
  return (
    <div className="poisson-section section-space">
      <div className="panel-title poisson-heading">
        <div>
          <span className="eyebrow">POISSON DISTRIBUTION</span>
          <h2>Probabilidades e odds justas</h2>
          <p>Expectativa automática de gols: <strong>{homeName} {Number(data.home_expectancy).toFixed(3)}</strong> · <strong>{awayName} {Number(data.away_expectancy).toFixed(3)}</strong> · <a href="https://sinceawin.com/poisson" target="_blank" rel="noreferrer">referência Poisson</a></p>
        </div>
      </div>

      <div className="poisson-grid top">
        <div className="poisson-card result-card">
          <h3><b>1X2</b> Full Time Result Odds</h3>
          <div className="poisson-result-boxes">
            <div className="poisson-result home"><span>Home Win</span><strong>{odd(data.result.home)}</strong><em>{pct(data.result.home)}</em></div>
            <div className="poisson-result draw"><span>Draw</span><strong>{odd(data.result.draw)}</strong><em>{pct(data.result.draw)}</em></div>
            <div className="poisson-result away"><span>Away Win</span><strong>{odd(data.result.away)}</strong><em>{pct(data.result.away)}</em></div>
          </div>
        </div>

        <div className="poisson-card">
          <h3><b>OU</b> Goals Over/Under</h3>
          <table className="poisson-table ou-table">
            <thead><tr><th></th>{data.over_under.map((x:any)=><th key={x.line}>{x.line}</th>)}</tr></thead>
            <tbody>
              <tr><th>Over</th>{data.over_under.map((x:any)=><td className="poisson-green" key={x.line}>{odd(x.over)}</td>)}</tr>
              <tr><th>Under</th>{data.over_under.map((x:any)=><td className="poisson-red" key={x.line}>{odd(x.under)}</td>)}</tr>
            </tbody>
          </table>
        </div>
      </div>

      <div className="poisson-grid bottom">
        <div className="poisson-card score-card">
          <h3><b>0–4</b> Correct Score Odds</h3>
          <div className="score-axis-label">Home Goals</div>
          <table className="poisson-table score-table">
            <thead><tr><th></th>{[0,1,2,3,4].map(x=><th key={x}>{x}</th>)}</tr></thead>
            <tbody>
              {data.correct_score.map((row:any)=><tr key={row.away_goals}>
                <th>{row.away_goals}</th>
                {row.cells.map((cell:any)=>{
                  const cls = cell.home_goals > cell.away_goals ? 'poisson-green' : cell.home_goals === cell.away_goals ? 'poisson-yellow' : 'poisson-red'
                  return <td className={cls} key={`${cell.home_goals}-${cell.away_goals}`}>{odd(cell)}</td>
                })}
              </tr>)}
            </tbody>
          </table>
          <div className="score-axis-footer">Away Goals</div>
        </div>

        <div className="poisson-card small-market-card">
          <h3><b>BTTS</b> Both Teams To Score Odds</h3>
          <table className="poisson-table compact"><thead><tr><th></th><th>Yes</th><th>No</th></tr></thead><tbody><tr><th>BTTS</th><td className="poisson-green">{odd(data.btts.yes)}</td><td className="poisson-red">{odd(data.btts.no)}</td></tr></tbody></table>
        </div>

        <div className="poisson-card small-market-card">
          <h3><b>CS</b> Clean Sheet Odds</h3>
          <table className="poisson-table compact"><thead><tr><th></th><th>Yes</th><th>No</th></tr></thead><tbody><tr><th>Home</th><td className="poisson-green">{odd(data.clean_sheet.home.yes)}</td><td className="poisson-red">{odd(data.clean_sheet.home.no)}</td></tr><tr><th>Away</th><td className="poisson-green">{odd(data.clean_sheet.away.yes)}</td><td className="poisson-red">{odd(data.clean_sheet.away.no)}</td></tr></tbody></table>
        </div>
      </div>
    </div>
  )
}
