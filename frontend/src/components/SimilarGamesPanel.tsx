import { useMemo, useState } from 'react'
import { api } from '../api'

type Props = {
  homeId: number
  awayId: number
  competitionId: number
  season: string
  homeName: string
  awayName: string
}

type MarketKey = 'home_win' | 'away_win' | 'over_15' | 'over_25' | 'btts'
const marketLabels: Record<MarketKey,string> = {
  home_win: 'Vitória do mandante',
  away_win: 'Vitória do visitante',
  over_15: 'Over 1,5',
  over_25: 'Over 2,5',
  btts: 'Ambos marcam',
}
const fmt=(v:any,d=1)=>v===null||v===undefined?'—':Number(v).toLocaleString('pt-BR',{minimumFractionDigits:d,maximumFractionDigits:d})
const signed=(v:any,d=1)=>v===null||v===undefined?'—':`${Number(v)>=0?'+':''}${fmt(v,d)}`

export default function SimilarGamesPanel({ homeId, awayId, competitionId, season, homeName, awayName }: Props) {
  const [homeOdd,setHomeOdd]=useState('')
  const [drawOdd,setDrawOdd]=useState('')
  const [awayOdd,setAwayOdd]=useState('')
  const [cutoff,setCutoff]=useState('')
  const [oddsTolerance,setOddsTolerance]=useState('10')
  const [eloTolerance,setEloTolerance]=useState('50')
  const [selected,setSelected]=useState<MarketKey[]>(['home_win'])
  const [extraOdds,setExtraOdds]=useState<Record<string,string>>({over_15:'',over_25:'',btts:''})
  const [data,setData]=useState<any>(null)
  const [loading,setLoading]=useState(false)
  const [error,setError]=useState('')

  const needsExtra = useMemo(()=>selected.filter(x=>['over_15','over_25','btts'].includes(x)),[selected])

  function toggle(market:MarketKey){
    setSelected(current=>current.includes(market)?current.filter(x=>x!==market):[...current,market])
  }
  const num=(v:string)=>Number(v.replace(',','.'))

  async function analyze(){
    setError('')
    if(!homeOdd||!drawOdd||!awayOdd){setError('Informe as três odds 1X2 para localizar jogos realmente semelhantes.');return}
    if(!selected.length){setError('Selecione pelo menos um mercado.');return}
    const tol=num(oddsTolerance)
    if(!Number.isFinite(tol)||tol<1||tol>50){setError('A faixa relativa das odds deve ficar entre 1% e 50%.');return}
    const eloTol=num(eloTolerance)
    if(!Number.isFinite(eloTol)||eloTol<5||eloTol>400){setError('A faixa da diferença de ELO deve ficar entre 5 e 400 pontos.');return}
    for(const market of needsExtra){if(!extraOdds[market]){setError(`Informe a odd de ${marketLabels[market]}.`);return}}
    try{
      setLoading(true)
      const result=await api<any>('/api/elo/similar-games',{
        method:'POST',
        body:JSON.stringify({
          home_id:homeId,away_id:awayId,competition_id:competitionId,season,
          home_odd:num(homeOdd),draw_odd:num(drawOdd),away_odd:num(awayOdd),
          odds_tolerance_pct:tol,
          elo_tolerance_points:eloTol,
          selected_markets:selected,
          market_odds:Object.fromEntries(needsExtra.map(m=>[m,num(extraOdds[m])])),
          cutoff_date:cutoff||null,
        })
      })
      setData(result)
    }catch(e:any){setError(e?.message||'Erro ao analisar jogos semelhantes.')}
    finally{setLoading(false)}
  }

  const elo=data?.elo_similarity

  return <div className="panel similar-panel section-space">
    <div className="panel-title"><div><span className="eyebrow">HISTORICAL MATCHING</span><h2>Jogos historicamente semelhantes</h2><p>Você controla a tolerância das odds e da diferença de ELO. Quanto menor a faixa, mais parecido é o cenário e menor tende a ser a amostra.</p></div></div>
    <div className="similar-form similar-form-wide">
      <div className="field"><label>Odd {homeName} *</label><input value={homeOdd} onChange={e=>setHomeOdd(e.target.value)} placeholder="Ex.: 1,65" inputMode="decimal"/></div>
      <div className="field"><label>Odd empate *</label><input value={drawOdd} onChange={e=>setDrawOdd(e.target.value)} placeholder="Ex.: 4,20" inputMode="decimal"/></div>
      <div className="field"><label>Odd {awayName} *</label><input value={awayOdd} onChange={e=>setAwayOdd(e.target.value)} placeholder="Ex.: 4,80" inputMode="decimal"/></div>
      <div className="field"><label>Faixa relativa das odds (%)</label><input type="number" min="1" max="50" step="0.5" value={oddsTolerance} onChange={e=>setOddsTolerance(e.target.value)}/><small>Ex.: 10 = cada odd 1/X/2 pode variar até ±10%.</small></div>
      <div className="field"><label>Faixa diferença ELO (pontos)</label><input type="number" min="5" max="400" step="5" value={eloTolerance} onChange={e=>setEloTolerance(e.target.value)}/><small>Compara ELO mandante − ELO visitante.</small></div>
      <div className="field"><label>Data limite</label><input value={cutoff} onChange={e=>setCutoff(e.target.value)} placeholder="dd/mm/aaaa"/><small>Vazio = todos os jogos antes de hoje.</small></div>
    </div>

    <div className="market-checks">
      {(Object.keys(marketLabels) as MarketKey[]).map(m=><label key={m}><input type="checkbox" checked={selected.includes(m)} onChange={()=>toggle(m)}/><span>{marketLabels[m]}</span></label>)}
    </div>

    {needsExtra.length>0&&<div className="similar-form extra-odds">{needsExtra.map(m=><div className="field" key={m}><label>Odd {marketLabels[m]} *</label><input value={extraOdds[m]} onChange={e=>setExtraOdds(x=>({...x,[m]:e.target.value}))} inputMode="decimal" placeholder="Odd atual"/></div>)}</div>}

    <div className="similar-actions"><button className="primary" onClick={analyze} disabled={loading}>{loading?'Analisando...':'Encontrar jogos semelhantes'}</button>{error&&<span className="inline-error">{error}</span>}</div>

    {data&&<>
      <div className="similar-meta"><span><small>Amostra por odds</small><strong>{data.sample_size?.toLocaleString('pt-BR')||0} jogos</strong></span><span><small>Faixa relativa usada</small><strong>{data.tolerance_pct!=null?`±${fmt(data.tolerance_pct,1)}%`:'—'}</strong></span><span><small>Jogos vinculados disponíveis</small><strong>{data.matched_available?.toLocaleString('pt-BR')||0}</strong></span><span><small>Até</small><strong>{data.cutoff_date?new Date(`${data.cutoff_date}T12:00:00`).toLocaleDateString('pt-BR'):'—'}</strong></span></div>
      {data.message&&<div className="notice info">{data.message}</div>}
      {data.sample_size>0&&<>
        <div className="similar-stats-grid">
          <span><small>Vitória mandante</small><strong>{fmt(data.summary.home_win_pct,1)}%</strong></span>
          <span><small>Empate</small><strong>{fmt(data.summary.draw_pct,1)}%</strong></span>
          <span><small>Vitória visitante</small><strong>{fmt(data.summary.away_win_pct,1)}%</strong></span>
          <span><small>Favorito venceu</small><strong>{fmt(data.summary.favorite_win_pct,1)}%</strong></span>
          <span><small>Zebra venceu</small><strong>{fmt(data.summary.underdog_win_pct,1)}%</strong></span>
          <span><small>Média gols mandante</small><strong>{fmt(data.summary.avg_home_goals,2)}</strong></span>
          <span><small>Média gols visitante</small><strong>{fmt(data.summary.avg_away_goals,2)}</strong></span>
          <span><small>Média geral de gols</small><strong>{fmt(data.summary.avg_total_goals,2)}</strong></span>
          <span><small>Over 1,5</small><strong>{fmt(data.summary.over_15_pct,1)}%</strong></span>
          <span><small>Over 2,5</small><strong>{fmt(data.summary.over_25_pct,1)}%</strong></span>
          <span><small>Ambos marcam</small><strong>{fmt(data.summary.btts_pct,1)}%</strong></span>
        </div>

        <div className="panel-title ev-title"><h3>EV esperado na odd informada</h3><span>EV = probabilidade histórica da amostra × odd atual − 1</span></div>
        <div className="table-scroll"><table className="ev-table"><thead><tr><th>Ano</th><th>Jogos</th>{selected.map(m=><th key={m}>{marketLabels[m]}</th>)}</tr></thead><tbody>
          {[...(data.ev_yearly||[]),data.ev_overall].filter(Boolean).map((row:any)=><tr key={row.period} className={row.period==='Geral'?'total-row':''}><td><strong>{row.period}</strong></td><td>{row.games?.toLocaleString('pt-BR')}</td>{selected.map(m=>{const x=row.markets?.[m];return <td key={m}>{x?<><strong className={x.ev_pct>=0?'ev-positive':'ev-negative'}>{x.ev_pct>=0?'+':''}{fmt(x.ev_pct,1)}%</strong><small>{fmt(x.hit_rate,1)}% acerto · odd {fmt(x.odd,2)}</small></>:'—'}</td>})}</tr>)}
        </tbody></table></div>

        <div className="panel-title similar-list-title"><h3>Jogos com odds semelhantes</h3><span>30 jogos mais próximos dentro da faixa de ±{fmt(data.tolerance_pct,1)}%</span></div>
        <div className="table-scroll"><table><thead><tr><th>Data</th><th>Campeonato</th><th>Mandante</th><th>Visitante</th><th>Placar</th><th>1</th><th>X</th><th>2</th><th>Desvio máx.</th></tr></thead><tbody>{data.similar_games?.map((g:any,i:number)=><tr key={`${g.date}-${g.home}-${i}`}><td>{new Date(`${g.date}T12:00:00`).toLocaleDateString('pt-BR')}</td><td>{g.competition}</td><td>{g.home}</td><td>{g.away}</td><td><strong>{g.score}</strong></td><td>{fmt(g.home_odd,2)}</td><td>{fmt(g.draw_odd,2)}</td><td>{fmt(g.away_odd,2)}</td><td>{fmt(g.max_relative_diff_pct,1)}%</td></tr>)}</tbody></table></div>
      </>}

      <div className="elo-similar-block">
        <div className="panel-title similar-list-title"><div><h3>Histórico com diferença de ELO semelhante</h3><span>Compara a diferença assinada ELO do mandante − ELO do visitante antes de cada jogo.</span></div></div>
        {elo?.available?<>
          <div className="similar-meta elo-meta"><span><small>Diferença atual</small><strong>{signed(elo.target_difference,1)} pts</strong></span><span><small>Faixa ELO</small><strong>±{fmt(elo.tolerance_points,0)} pts</strong></span><span><small>Amostra ELO</small><strong>{elo.sample_size?.toLocaleString('pt-BR')||0} jogos</strong></span><span><small>ELO atual</small><strong>{fmt(elo.current_home_elo,1)} × {fmt(elo.current_away_elo,1)}</strong></span></div>
          {elo.message&&<div className="notice info">{elo.message}</div>}
          {elo.sample_size>0&&<>
            <div className="similar-stats-grid elo-summary-grid">
              <span><small>Vitória mandante</small><strong>{fmt(elo.summary.home_win_pct,1)}%</strong></span>
              <span><small>Empate</small><strong>{fmt(elo.summary.draw_pct,1)}%</strong></span>
              <span><small>Vitória visitante</small><strong>{fmt(elo.summary.away_win_pct,1)}%</strong></span>
              <span><small>Média geral gols</small><strong>{fmt(elo.summary.avg_total_goals,2)}</strong></span>
              <span><small>Over 1,5</small><strong>{fmt(elo.summary.over_15_pct,1)}%</strong></span>
              <span><small>Over 2,5</small><strong>{fmt(elo.summary.over_25_pct,1)}%</strong></span>
              <span><small>Ambos marcam</small><strong>{fmt(elo.summary.btts_pct,1)}%</strong></span>
            </div>

            <div className="panel-title ev-title elo-ev-title">
              <h3>EV pelo histórico de ELO semelhante</h3>
              <span>EV = probabilidade histórica da amostra por diferença de ELO × odd atual − 1</span>
            </div>
            <div className="table-scroll">
              <table className="ev-table">
                <thead>
                  <tr>
                    <th>Ano</th>
                    <th>Jogos</th>
                    {selected.map(m=><th key={`elo-head-${m}`}>{marketLabels[m]}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {[...(elo.ev_yearly||[]),elo.ev_overall].filter(Boolean).map((row:any)=>
                    <tr key={`elo-ev-${row.period}`} className={row.period==='Geral'?'total-row':''}>
                      <td><strong>{row.period}</strong></td>
                      <td>{row.games?.toLocaleString('pt-BR')}</td>
                      {selected.map(m=>{
                        const x=row.markets?.[m]
                        return <td key={`elo-${row.period}-${m}`}>
                          {x
                            ? <>
                                <strong className={x.ev_pct>=0?'ev-positive':'ev-negative'}>
                                  {x.ev_pct>=0?'+':''}{fmt(x.ev_pct,1)}%
                                </strong>
                                <small>{fmt(x.hit_rate,1)}% acerto · odd {fmt(x.odd,2)}</small>
                              </>
                            : '—'}
                        </td>
                      })}
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            <div className="panel-title similar-list-title">
              <h3>Jogos com diferença de ELO semelhante</h3>
              <span>30 jogos mais próximos dentro da faixa de ±{fmt(elo.tolerance_points,0)} pontos</span>
            </div>
            <div className="table-scroll"><table><thead><tr><th>Data</th><th>Campeonato</th><th>Mandante</th><th>Visitante</th><th>Placar</th><th>ELO Casa</th><th>ELO Fora</th><th>Diferença</th><th>Distância</th></tr></thead><tbody>{elo.games?.map((g:any,i:number)=><tr key={`elo-${g.date}-${g.home}-${i}`}><td>{new Date(`${g.date}T12:00:00`).toLocaleDateString('pt-BR')}</td><td>{g.competition}</td><td>{g.home}</td><td>{g.away}</td><td><strong>{g.score}</strong></td><td>{fmt(g.home_elo,1)}</td><td>{fmt(g.away_elo,1)}</td><td>{signed(g.elo_difference,1)}</td><td>{fmt(g.distance_points,1)} pts</td></tr>)}</tbody></table></div>
          </>}
        </>:<div className="notice info">{elo?.message||'ELO histórico ainda não disponível para este confronto.'}</div>}
      </div>
    </>}
  </div>
}
