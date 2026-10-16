import { useEffect, useMemo, useRef, useState } from 'react'
import { api, query } from '../api'

type Match = {
  id: number
  nome: string
  pais: string
  escudo_url?: string
  ja_cadastrado?: boolean
  historico?: string
}

export type ImportAdditionalClub = {
  key: number
  nome: string
  clube_id: number | null
}

type Props = {
  value: ImportAdditionalClub
  competitionId: number
  season: string
  excludedClubIds: number[]
  onChange: (value: ImportAdditionalClub) => void
  onRemove: () => void
}

export default function CompetitionClubLookup({
  value,
  competitionId,
  season,
  excludedClubIds,
  onChange,
  onRemove,
}: Props) {
  const [results, setResults] = useState<Match[]>([])
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const requestRef = useRef(0)

  const excluded = useMemo(() => new Set(excludedClubIds), [excludedClubIds])

  const visibleResults = useMemo(
    () => results.filter(item => !excluded.has(item.id)),
    [results, excluded],
  )

  async function loadOptions(term = value.nome) {
    if (!competitionId || value.clube_id) return

    const requestId = ++requestRef.current
    setLoading(true)
    try {
      const data = await api<Match[]>(
        `/api/manage/clubs/search-competition-base?${query({
          campeonato_id: competitionId,
          temporada: season,
          q: term.trim() || undefined,
          limit: 300,
        })}`,
      )

      if (requestId === requestRef.current) {
        setResults(data)
        setOpen(true)
      }
    } finally {
      if (requestId === requestRef.current) setLoading(false)
    }
  }

  useEffect(() => {
    if (value.clube_id) {
      setResults([])
      setOpen(false)
      return
    }

    if (!value.nome.trim()) {
      setResults([])
      return
    }

    const timer = window.setTimeout(() => {
      loadOptions(value.nome)
    }, 160)

    return () => window.clearTimeout(timer)
  }, [value.nome, value.clube_id, competitionId, season])

  return (
    <div className="additional-club-row">
      <div className="additional-club-lookup">
        <div className="field">
          <label>Clube</label>
          <div className="additional-club-input-wrap">
            <input
              value={value.nome}
              placeholder="Selecione ou digite o nome do clube..."
              autoComplete="off"
              onFocus={() => {
                if (!value.clube_id) loadOptions(value.nome)
              }}
              onBlur={() => window.setTimeout(() => setOpen(false), 160)}
              onChange={e => {
                onChange({ ...value, nome: e.target.value, clube_id: null })
                setOpen(true)
              }}
            />
            <button
              type="button"
              className="additional-club-dropdown-button"
              tabIndex={-1}
              onMouseDown={e => e.preventDefault()}
              onClick={() => {
                if (open) setOpen(false)
                else loadOptions(value.nome)
              }}
              title="Mostrar clubes cadastrados no campeonato"
            >
              ▾
            </button>
          </div>
        </div>

        {open && !value.clube_id && (
          <div className="additional-club-results">
            {loading ? (
              <div className="additional-club-empty">Carregando clubes...</div>
            ) : visibleResults.length ? (
              visibleResults.map(item => (
                <button
                  key={item.id}
                  type="button"
                  onMouseDown={e => e.preventDefault()}
                  onClick={() => {
                    onChange({ ...value, nome: item.nome, clube_id: item.id })
                    setOpen(false)
                  }}
                >
                  <span className="club-inline">
                    {item.escudo_url
                      ? <img src={item.escudo_url} alt="" />
                      : <span className="mini-crest">{item.nome[0]}</span>}
                    <strong>{item.nome}</strong>
                  </span>
                  <span className="lookup-result-meta">
                    {item.historico && <small>Temporadas: {item.historico}</small>}
                    <span className={`import-status ${item.ja_cadastrado ? 'existing' : 'new'}`}>
                      {item.ja_cadastrado ? 'Já está no destino' : 'Usar cadastro existente'}
                    </span>
                  </span>
                </button>
              ))
            ) : value.nome.trim() ? (
              <div className="additional-club-empty">
                Nenhum clube cadastrado neste campeonato corresponde à busca. Ao importar, será criado apenas com o nome digitado.
              </div>
            ) : (
              <div className="additional-club-empty">
                Todos os clubes disponíveis deste campeonato já estão selecionados para a importação.
              </div>
            )}
          </div>
        )}
      </div>

      <div className="additional-club-status">
        {value.clube_id ? (
          <span className="import-status existing">Usar cadastro existente</span>
        ) : value.nome.trim() ? (
          <span className="import-status new">Cadastrar se for inédito</span>
        ) : (
          <span>—</span>
        )}
      </div>

      <button
        type="button"
        className="additional-club-remove"
        onClick={onRemove}
        title="Remover linha"
      >
        ×
      </button>
    </div>
  )
}
