import { useEffect, useState } from 'react'
import { api, query } from '../api'
import IdAutocomplete from '../components/IdAutocomplete'
import StatBar from '../components/StatBar'
import EloChart from '../components/EloChart'
import SimilarGamesPanel from '../components/SimilarGamesPanel'
import PoissonBoard from '../components/PoissonBoard'
import RadarChart from '../components/RadarChart'

type Item = {
  id: number
  nome: string
  principal?: boolean
  escudo_url?: string
}

type MainTab = 'market' | 'direct'
type DirectMode = 'general' | 'venue'

const fmt = (n: any, d = 1) =>
  n === null || n === undefined
    ? '—'
    : Number(n).toLocaleString('pt-BR', {
        minimumFractionDigits: d,
        maximumFractionDigits: d,
      })

function TeamStats({ title, data }: { title: string; data: any }) {
  if (!data) return null

  return (
    <div className="team-stat-panel">
      <h3>{title}</h3>

      <StatBar label="Vitórias" value={data.wins_pct} suffix="%" />
      <StatBar label="Empates" value={data.draws_pct} suffix="%" />
      <StatBar label="Derrotas" value={data.losses_pct} suffix="%" />
      <StatBar label="Over 0,5" value={data.over_05_pct} suffix="%" />
      <StatBar label="Over 1,5" value={data.over_15_pct} suffix="%" />
      <StatBar label="Over 2,5" value={data.over_25_pct} suffix="%" />
      <StatBar label="Ambos marcam" value={data.btts_pct} suffix="%" />

      <div className="numeric-stats">
        <span><small>Média gols marcados</small><strong>{fmt(data.avg_goals_for, 2)}</strong></span>
        <span><small>Média gols sofridos</small><strong>{fmt(data.avg_goals_against, 2)}</strong></span>
        <span><small>Odd média</small><strong>{data.avg_odd ? fmt(data.avg_odd, 2) : '—'}</strong></span>
        <span><small>Custo do gol 1.0</small><strong>{data.cost_goal_1 ? fmt(data.cost_goal_1, 2) : '—'}</strong></span>
        <span><small>CV CG 1.0</small><strong>{data.cv_cost_goal_1 ? `${fmt(data.cv_cost_goal_1, 1)}%` : '—'}</strong></span>
        <span><small>Custo do gol 2.0</small><strong>{data.cost_goal_2 ? fmt(data.cost_goal_2, 2) : '—'}</strong></span>
        <span><small>CV CG 2.0</small><strong>{data.cv_cost_goal_2 ? `${fmt(data.cv_cost_goal_2, 1)}%` : '—'}</strong></span>
      </div>
    </div>
  )
}

function DirectBlock({
  title,
  data,
  homeName,
  awayName,
}: {
  title: string
  data: any
  homeName: string
  awayName: string
}) {
  if (!data) return null

  return (
    <div className="direct-block">
      <div className="direct-block-head">
        <h3>{title}</h3>
        <span>{data.games.toLocaleString('pt-BR')} jogos</span>
      </div>

      <div className="direct-kpi-grid">
        <div><small>Jogos</small><strong>{data.games.toLocaleString('pt-BR')}</strong></div>
        <div><small>Vitórias {homeName}</small><strong>{data.home_wins.toLocaleString('pt-BR')}</strong></div>
        <div><small>% Vitórias {homeName}</small><strong>{fmt(data.home_wins_pct, 1)}%</strong></div>
        <div><small>Empates</small><strong>{data.draws.toLocaleString('pt-BR')}</strong></div>
        <div><small>Vitórias {awayName}</small><strong>{data.away_wins.toLocaleString('pt-BR')}</strong></div>
        <div><small>% Vitórias {awayName}</small><strong>{fmt(data.away_wins_pct, 1)}%</strong></div>
        <div><small>Gols {homeName}</small><strong>{data.home_goals.toLocaleString('pt-BR')}</strong></div>
        <div><small>Gols {awayName}</small><strong>{data.away_goals.toLocaleString('pt-BR')}</strong></div>
        <div><small>Média de gols do confronto</small><strong>{fmt(data.avg_goals, 2)}</strong></div>
        <div><small>Over 0,5</small><strong>{fmt(data.over_05_pct, 1)}%</strong></div>
        <div><small>Over 1,5</small><strong>{fmt(data.over_15_pct, 1)}%</strong></div>
        <div><small>Over 2,5</small><strong>{fmt(data.over_25_pct, 1)}%</strong></div>
        <div><small>Ambos marcam</small><strong>{fmt(data.btts_pct, 1)}%</strong></div>
      </div>
    </div>
  )
}

export default function Backtest() {
  const [countries, setCountries] = useState<Item[]>([])
  const [seasons, setSeasons] = useState<string[]>([])
  const [competitions, setCompetitions] = useState<Item[]>([])
  const [clubs, setClubs] = useState<Item[]>([])

  const [country, setCountry] = useState<Item | null>(null)
  const [season, setSeason] = useState('')
  const [competition, setCompetition] = useState<Item | null>(null)
  const [home, setHome] = useState<Item | null>(null)
  const [away, setAway] = useState<Item | null>(null)

  const [period, setPeriod] = useState('10')
  const [backtest, setBacktest] = useState<any>(null)
  const [mainTab, setMainTab] = useState<MainTab>('market')
  const [resultTab, setResultTab] = useState<'general' | 'venue'>('general')
  const [directMode, setDirectMode] = useState<DirectMode>('general')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    api<any>('/api/elo/filters').then(d => {
      setCountries(d.countries)
      setSeasons(d.seasons)
      if (d.seasons?.length) setSeason(d.seasons[0])
    })
  }, [])

  useEffect(() => {
    setBacktest(null)
    setHome(null)
    setAway(null)

    if (!country) {
      setCompetitions([])
      setCompetition(null)
      return
    }

    api<Item[]>(`/api/elo/competitions?country_id=${country.id}`).then(d => {
      setCompetitions(d)
      setCompetition(d.find(x => x.principal) || d[0] || null)
    })
  }, [country?.id])

  useEffect(() => {
    setBacktest(null)
    setHome(null)
    setAway(null)

    if (!competition || !season) {
      setClubs([])
      return
    }

    api<Item[]>(
      `/api/elo/clubs?${query({
        country_id: country?.id,
        competition_id: competition.id,
        season,
      })}`,
    ).then(setClubs)
  }, [competition?.id, season])

  async function runBacktest(requestedPeriod = period) {
    if (!home || !away || !competition || !season) return
    setLoading(true)
    setError('')
    try {
      const data = await api<any>(
        `/api/elo/backtest?${query({
          home_id: home.id,
          away_id: away.id,
          competition_id: competition.id,
          season,
          period: requestedPeriod,
        })}`,
      )
      setBacktest(data)
      setResultTab('general')
      setDirectMode('general')
    } catch (err: any) {
      setError(err?.message || 'Não foi possível atualizar o confronto.')
    } finally {
      setLoading(false)
    }
  }

  const result = backtest?.[resultTab]
  const direct = backtest?.direct_confrontation?.[directMode]

  return (
    <section className="page backtest-page">
      <div className="page-header backtest-page-title">
        <div>
          <span className="eyebrow">MATCH ANALYSIS</span>
          <h1>Backtest</h1>
          <p>
            Compare mercado, ELO, desempenho e histórico direto entre os clubes.
          </p>
        </div>
      </div>

      <div className="backtest-sticky-head">
        <div className="panel backtest-filter-panel">
          <div className="backtest-filter-grid backtest-filter-grid-fixed">
            <IdAutocomplete
              label="País"
              value={country}
              options={countries}
              onChange={setCountry}
            />

            <div className="field">
              <label>Temporada</label>
              <select value={season} onChange={e => setSeason(e.target.value)}>
                {seasons.map(s => <option key={s}>{s}</option>)}
              </select>
            </div>

            <IdAutocomplete
              label="Campeonato"
              value={competition}
              options={competitions}
              onChange={setCompetition}
              disabled={!country}
            />

            <IdAutocomplete
              label="Mandante"
              value={home}
              options={clubs.filter(c => c.id !== away?.id)}
              onChange={setHome}
              disabled={!competition}
            />

            <IdAutocomplete
              label="Visitante"
              value={away}
              options={clubs.filter(c => c.id !== home?.id)}
              onChange={setAway}
              disabled={!competition}
            />

            <div className="form-actions">
              <button
                className="primary"
                onClick={() => runBacktest(period)}
                disabled={!home || !away || loading}
              >
                {loading ? 'Analisando...' : 'Analisar confronto'}
              </button>
            </div>
          </div>
        </div>

        <div className="backtest-main-tabs">
          <button
            className={mainTab === 'market' ? 'active' : ''}
            onClick={() => setMainTab('market')}
          >
            Mercado
          </button>

          <button
            className={mainTab === 'direct' ? 'active' : ''}
            onClick={() => setMainTab('direct')}
          >
            Confronto Direto
          </button>
        </div>
      </div>

      {error && <div className="notice error backtest-error">{error}</div>}

      {!backtest && (
        <div className="panel empty-state backtest-empty">
          Selecione os dois clubes e clique em <strong>Analisar confronto</strong>.
        </div>
      )}

      {backtest && mainTab === 'market' && (
        <>
          <div className="panel market-period-panel">
            <div className="field market-period-field">
              <label>Recorte estatístico do mercado</label>
              <select value={period} onChange={e => setPeriod(e.target.value)}>
                <option value="5">Últimos 5 jogos</option>
                <option value="10">Últimos 10 jogos</option>
                <option value="20">Últimos 20 jogos</option>
                <option value="season">Temporada inteira</option>
              </select>
            </div>

            <button
              className="secondary"
              onClick={() => runBacktest(period)}
              disabled={!home || !away || loading}
            >
              {loading ? 'Atualizando...' : 'Atualizar recorte'}
            </button>
          </div>

          {backtest.strengths && (
            <div className="panel pad section-space">
              <div className="panel-title">
                <div>
                  <h2>Força ofensiva e defensiva</h2>
                  <span>Comparação geral e específica do mando deste confronto{backtest.strengths.reference_season?` · referência ${backtest.strengths.reference_season}`:''}{backtest.strengths.used_fallback_season?` (última temporada com jogos até ${season})`:''}</span>
                </div>
                <span>Força defensiva: menor = melhor</span>
              </div>

              <RadarChart
                labelA={home?.nome || 'Mandante'}
                labelB={away?.nome || 'Visitante'}
                axes={[
                  {
                    label: 'Ataque geral',
                    a: backtest.strengths.home.attack_general,
                    b: backtest.strengths.away.attack_general,
                  },
                  {
                    label: 'Defesa geral',
                    a: backtest.strengths.home.defense_general,
                    b: backtest.strengths.away.defense_general,
                    lowerBetter: true,
                  },
                  {
                    label: 'Ataque no mando',
                    a: backtest.strengths.home.attack_venue,
                    b: backtest.strengths.away.attack_venue,
                  },
                  {
                    label: 'Defesa no mando',
                    a: backtest.strengths.home.defense_venue,
                    b: backtest.strengths.away.defense_venue,
                    lowerBetter: true,
                  },
                ]}
                note="1,00 representa a média da competição. Defesa menor é melhor; no radar o eixo defensivo é invertido apenas visualmente para que uma área maior represente melhor desempenho."
              />
            </div>
          )}

          <div className="panel pad section-space elo-evolution-panel">
            <div className="panel-title">
              <h2>Evolução do ELO</h2>

              <div className="elo-deltas">
                <span>
                  5j: {backtest.elo_evolution.home.delta['5'] ?? '—'} /{' '}
                  {backtest.elo_evolution.away.delta['5'] ?? '—'}
                </span>
                <span>
                  10j: {backtest.elo_evolution.home.delta['10'] ?? '—'} /{' '}
                  {backtest.elo_evolution.away.delta['10'] ?? '—'}
                </span>
                <span>
                  20j: {backtest.elo_evolution.home.delta['20'] ?? '—'} /{' '}
                  {backtest.elo_evolution.away.delta['20'] ?? '—'}
                </span>
              </div>
            </div>

            <EloChart
              home={backtest.elo_evolution.home.series}
              away={backtest.elo_evolution.away.series}
              homeName={home?.nome || 'Mandante'}
              awayName={away?.nome || 'Visitante'}
            />

            {backtest.elo_probability && (
              <div className="prob-strip">
                <div>
                  <span>{home?.nome}</span>
                  <strong>{fmt(backtest.elo_probability.home * 100, 1)}%</strong>
                </div>
                <div>
                  <span>Empate</span>
                  <strong>{fmt(backtest.elo_probability.draw * 100, 1)}%</strong>
                </div>
                <div>
                  <span>{away?.nome}</span>
                  <strong>{fmt(backtest.elo_probability.away * 100, 1)}%</strong>
                </div>
              </div>
            )}
          </div>

          <div className="result-tabs">
            <button
              className={resultTab === 'general' ? 'active' : ''}
              onClick={() => setResultTab('general')}
            >
              Geral
            </button>
            <button
              className={resultTab === 'venue' ? 'active' : ''}
              onClick={() => setResultTab('venue')}
            >
              Por Mando
            </button>
          </div>

          <div className="compare-grid">
            <TeamStats title={home?.nome || 'Mandante'} data={result?.home} />
            <TeamStats title={away?.nome || 'Visitante'} data={result?.away} />
          </div>

          <PoissonBoard
            data={backtest.poisson}
            homeName={home?.nome || 'Mandante'}
            awayName={away?.nome || 'Visitante'}
          />

          {home && away && competition && (
            <SimilarGamesPanel
              homeId={home.id}
              awayId={away.id}
              competitionId={competition.id}
              season={season}
              homeName={home.nome}
              awayName={away.nome}
            />
          )}
        </>
      )}

      {backtest && mainTab === 'direct' && (
        <div className="direct-section">
          <div className="panel direct-intro">
            <div>
              <span className="eyebrow">HEAD TO HEAD</span>
              <h2>{home?.nome} × {away?.nome}</h2>
              <p>
                Histórico até a temporada {season}. No modo Geral, o mando histórico
                é ignorado e os números são apresentados pela perspectiva dos clubes
                selecionados. Em Por Mando, entram apenas partidas com {home?.nome} em
                casa e {away?.nome} fora.
              </p>
            </div>

            <div className="direct-mode-tabs">
              <button
                className={directMode === 'general' ? 'active' : ''}
                onClick={() => setDirectMode('general')}
              >
                Geral
              </button>
              <button
                className={directMode === 'venue' ? 'active' : ''}
                onClick={() => setDirectMode('venue')}
              >
                Por Mando
              </button>
            </div>
          </div>

          <div className="direct-blocks-grid">
            <DirectBlock
              title="Últimos 5 jogos"
              data={direct?.['5']}
              homeName={home?.nome || 'Mandante'}
              awayName={away?.nome || 'Visitante'}
            />
            <DirectBlock
              title="Últimos 10 jogos"
              data={direct?.['10']}
              homeName={home?.nome || 'Mandante'}
              awayName={away?.nome || 'Visitante'}
            />
            <DirectBlock
              title="Últimos 20 jogos"
              data={direct?.['20']}
              homeName={home?.nome || 'Mandante'}
              awayName={away?.nome || 'Visitante'}
            />
            <DirectBlock
              title="Todo o histórico"
              data={direct?.all}
              homeName={home?.nome || 'Mandante'}
              awayName={away?.nome || 'Visitante'}
            />
          </div>
        </div>
      )}
    </section>
  )
}
