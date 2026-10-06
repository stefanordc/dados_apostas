import { useEffect, useMemo, useRef, useState } from 'react'
import { api, query } from '../api'
import IdAutocomplete from '../components/IdAutocomplete'
import CrudDataFrame, { type CrudColumn } from '../components/CrudDataFrame'
import Modal from '../components/Modal'
import CompetitionClubLookup, { type ImportAdditionalClub } from '../components/CompetitionClubLookup'

type Item = {
  id: number
  nome: string
  pais_id?: number
  pais?: string
  continente?: string
  principal?: boolean
  escudo_url?: string
}

type MarketRow = {
  id: number
  temporada: string
  pais_id: number
  pais: string
  campeonato_id: number
  campeonato: string
  clube_id: number
  clube: string
  escudo_url?: string
  valor: number
  moeda: string
  atualizado_em?: string
}

type CountryRow = {
  id: number
  nome: string
  continente: string
  criado_em?: string
}

type CompetitionRow = {
  id: number
  nome: string
  pais_id: number
  pais: string
  principal: boolean
  criado_em?: string
}

type ClubRow = {
  id: number
  nome: string
  pais_id: number
  pais: string
  escudo_url?: string
  vinculos?: string
  criado_em?: string
}

type ImportClubRow = {
  id: number
  nome: string
  pais: string
  escudo_url?: string
  ja_cadastrado: boolean
}

type ImportPreview = {
  campeonato?: { id: number; nome: string; pais: string } | null
  temporada_origem: string
  temporada_destino: string
  clubes: ImportClubRow[]
}

type PageResponse<T> = {
  rows: T[]
  total: number
  page: number
  page_size: number
  pages: number
}

type Tab = 'valor' | 'clubes' | 'campeonatos' | 'paises'
type AnyRow = MarketRow | CountryRow | CompetitionRow | ClubRow

const PAGE_SIZE = 20

const money = (v: number | string | null | undefined, c: string | null | undefined) => {
  const numeric = Number(v)
  if (!Number.isFinite(numeric)) return '—'

  const currency = c === 'BRL' || c === 'USD' || c === 'EUR' ? c : null
  if (!currency) return numeric.toLocaleString('pt-BR')

  return new Intl.NumberFormat(
    currency === 'BRL' ? 'pt-BR' : currency === 'USD' ? 'en-US' : 'de-DE',
    { style: 'currency', currency, maximumFractionDigits: 0 },
  ).format(numeric)
}

function quickMarketBulkSummary(raw:string){
  const lines=raw.split(/\r?\n/).map(x=>x.trim()).filter(Boolean)
  if(!lines.length)return {total_rows:0,seasons:[] as string[]}

  let rows:string[][]=[]
  if(lines[0].includes('|')){
    const split=(line:string)=>line.replace(/^\|/,'').replace(/\|$/,'').split('|').map(x=>x.trim())
    const start=lines.length>1&&split(lines[1]).every(x=>/^:?-{3,}:?$/.test(x))?2:1
    rows=lines.slice(start).map(split).filter(r=>r.length>=3)
  }else if(lines[0].includes('\t')){
    rows=lines.slice(1).map(line=>line.split('\t').map(x=>x.trim())).filter(r=>r.length>=3)
  }else{
    const firstLooksHeader=/temporada/i.test(lines[0])&&/clube/i.test(lines[0])
    rows=lines.slice(firstLooksHeader?1:0).map(line=>line.split(/\s{2,}/).map(x=>x.trim())).filter(r=>r.length>=3)
  }
  const valid=rows.filter(r=>/^\d{4}\/\d{4}$/.test(r[0]||''))
  return {total_rows:valid.length,seasons:[...new Set(valid.map(r=>r[0]))].sort()}
}

export default function Cadastros() {
  const [tab, setTab] = useState<Tab>('valor')
  const [countries, setCountries] = useState<Item[]>([])
  const [competitions, setCompetitions] = useState<Item[]>([])
  const [clubs, setClubs] = useState<Item[]>([])

  const [country, setCountry] = useState<Item | null>(null)
  const [competition, setCompetition] = useState<Item | null>(null)
  const [club, setClub] = useState<Item | null>(null)
  const [season, setSeason] = useState('')
  const [value, setValue] = useState('')
  const [currency, setCurrency] = useState('EUR')
  const [msg, setMsg] = useState('')
  const [marketBulkRaw, setMarketBulkRaw] = useState('')
  const [marketBulkPreview, setMarketBulkPreview] = useState<any>(null)
  const [marketBulkError, setMarketBulkError] = useState('')
  const [marketBulkLoading, setMarketBulkLoading] = useState(false)
  const [marketImports, setMarketImports] = useState<any[]>([])
  const [marketImportsLoading, setMarketImportsLoading] = useState(false)

  const [countryName, setCountryName] = useState('')
  const [continent, setContinent] = useState('Europa')
  const [competitionName, setCompetitionName] = useState('')
  const [principal, setPrincipal] = useState(false)
  const [clubName, setClubName] = useState('')
  const [crest, setCrest] = useState('')

  const [gridRows, setGridRows] = useState<AnyRow[]>([])
  const [gridTotal, setGridTotal] = useState(0)
  const [gridPage, setGridPage] = useState(1)
  const [gridSearch, setGridSearch] = useState('')
  const [gridLoading, setGridLoading] = useState(false)
  const gridRequestRef = useRef(0)
  const [clubFilterSeason, setClubFilterSeason] = useState('')
  const [clubFilterCountry, setClubFilterCountry] = useState<Item | null>(null)
  const [clubFilterCompetition, setClubFilterCompetition] = useState<Item | null>(null)
  const [clubFilterCompetitions, setClubFilterCompetitions] = useState<Item[]>([])
  const [editing, setEditing] = useState<AnyRow | null>(null)
  const [clubDetail, setClubDetail] = useState<any>(null)

  const [editCompetitions, setEditCompetitions] = useState<Item[]>([])
  const [editClubs, setEditClubs] = useState<Item[]>([])
  const [importPreview, setImportPreview] = useState<ImportPreview | null>(null)
  const [importSelected, setImportSelected] = useState<Set<number>>(new Set())
  const [importAdditional, setImportAdditional] = useState<ImportAdditionalClub[]>([])
  const [importAdditionalKey, setImportAdditionalKey] = useState(1)
  const [importLoading, setImportLoading] = useState(false)

  const loadCountries = () => api<Item[]>('/api/countries').then(setCountries)

  const loadClubs = (
    cid = country?.id,
    comp = competition?.id,
    s = season,
    exclude = tab === 'valor',
  ) => {
    if (!cid) {
      setClubs([])
      return
    }
    api<Item[]>(
      `/api/clubs?${query({
        country_id: cid,
        competition_id: comp,
        season: comp && s ? s : undefined,
        exclude_market_values: exclude && comp && s ? 'true' : undefined,
      })}`,
    ).then(setClubs)
  }

  const gridEndpoint = useMemo(() => {
    if (tab === 'valor') return '/api/manage/market-values'
    if (tab === 'clubes') return '/api/manage/clubs'
    if (tab === 'campeonatos') return '/api/manage/competitions'
    return '/api/manage/countries'
  }, [tab])

  async function loadGrid(page = gridPage, search = gridSearch) {
    const requestId = ++gridRequestRef.current
    const endpoint = gridEndpoint
    const currentTab = tab

    setGridLoading(true)
    try {
      const data = await api<PageResponse<AnyRow>>(
        `${endpoint}?${query({
          q: search || undefined,
          page,
          page_size: PAGE_SIZE,
          temporada: currentTab === 'clubes' ? clubFilterSeason || undefined : undefined,
          pais_id: currentTab === 'clubes' ? clubFilterCountry?.id : undefined,
          campeonato_id: currentTab === 'clubes' ? clubFilterCompetition?.id : undefined,
        })}`,
      )

      // Ignora respostas de uma aba anterior que terminarem depois da troca de aba.
      if (requestId !== gridRequestRef.current) return

      setGridRows(data.rows)
      setGridTotal(data.total)
    } finally {
      if (requestId === gridRequestRef.current) setGridLoading(false)
    }
  }

  useEffect(() => {
    loadCountries()
    loadMarketImports()
  }, [])

  useEffect(() => {
    if(tab==='valor') loadMarketImports()
  }, [tab])

  useEffect(() => {
    if (!country) {
      setCompetitions([])
      setCompetition(null)
      setClubs([])
      return
    }
    api<Item[]>(`/api/competitions?country_id=${country.id}`).then(setCompetitions)
    setCompetition(null)
    setClub(null)
    loadClubs(country.id, undefined, season)
  }, [country?.id])

  useEffect(() => {
    setClub(null)
    loadClubs(country?.id, competition?.id, season, tab === 'valor')
  }, [competition?.id, season, tab])

  useEffect(() => {
    // Ao trocar de aba, elimina imediatamente as linhas da aba anterior.
    // Isso evita que colunas de Valor de Mercado tentem renderizar objetos de Clubes.
    gridRequestRef.current += 1
    setGridRows([])
    setGridTotal(0)
    setGridLoading(true)
    setGridPage(1)
    setGridSearch('')
    setEditing(null)
    setClubDetail(null)
  }, [tab])

  useEffect(() => {
    setGridPage(1)
    setClubFilterCompetition(null)

    if (!clubFilterCountry) {
      setClubFilterCompetitions([])
      return
    }

    api<Item[]>(
      `/api/competitions?${query({ country_id: clubFilterCountry.id })}`,
    ).then(setClubFilterCompetitions)
  }, [clubFilterCountry?.id])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      loadGrid(gridPage, gridSearch)
    }, 180)
    return () => window.clearTimeout(timer)
  }, [
    gridEndpoint,
    gridPage,
    gridSearch,
    clubFilterSeason,
    clubFilterCountry?.id,
    clubFilterCompetition?.id,
  ])

  function changeTab(nextTab: Tab) {
    if (nextTab === tab) return

    // React agrupa estas alterações no mesmo render. Assim a nova aba nunca
    // recebe as linhas/colunas da aba anterior, evitando o crash no formatter.
    gridRequestRef.current += 1
    setGridRows([])
    setGridTotal(0)
    setGridLoading(true)
    setGridPage(1)
    setGridSearch('')
    setEditing(null)
    setClubDetail(null)
    setTab(nextTab)
  }

  async function refreshEverything() {
    await loadCountries()
    if (country?.id) {
      setCompetitions(await api<Item[]>(`/api/competitions?country_id=${country.id}`))
      loadClubs()
    }
    await loadGrid()
  }

  async function saveMarket(e: React.FormEvent) {
    e.preventDefault()
    if (!season || !country || !competition || !club || !value) {
      return setMsg('Preencha todos os campos obrigatórios.')
    }
    const n = Number(value.replace(/\./g, '').replace(',', '.'))
    if (!Number.isFinite(n) || n <= 0) return setMsg('Valor inválido.')

    const result: any = await api('/api/market-values', {
      method: 'POST',
      body: JSON.stringify({
        temporada: season,
        pais_id: country.id,
        campeonato_id: competition.id,
        clube_id: club.id,
        valor: n,
        moeda: currency,
      }),
    })

    setMsg(
      result?.elo?.status === 'ok'
        ? 'Valor salvo e ELO da temporada recalculado.'
        : 'Valor de mercado salvo.',
    )
    setValue('')
    setClub(null)
    await Promise.all([
      loadGrid(1, gridSearch),
      Promise.resolve(loadClubs(country.id, competition.id, season)),
    ])
    setGridPage(1)
  }

  async function loadMarketImports() {
    setMarketImportsLoading(true)
    try {
      setMarketImports(await api<any[]>('/api/market-values/bulk/imports?limit=10'))
    } finally {
      setMarketImportsLoading(false)
    }
  }

  async function deleteMarketImport(id:number){
    if(!window.confirm('Excluir esta carga de valores de mercado? Os valores ainda vinculados a ela serão removidos.'))return
    setMarketBulkError('')
    try{
      const result=await api<any>(`/api/market-values/bulk/imports/${id}`,{method:'DELETE'})
      setMsg(`Carga #${id} excluída (${Number(result.deleted_rows||0).toLocaleString('pt-BR')} valores removidos).`)
      await Promise.all([loadMarketImports(),loadGrid(1,gridSearch)])
    }catch(error){
      setMarketBulkError(error instanceof Error?error.message:'Não foi possível excluir a carga.')
    }
  }

  function previewMarketBulk() {
    setMarketBulkError('')
    if (!marketBulkRaw.trim()) return setMarketBulkError('Cole os valores de mercado antes de validar.')
    if (!country) return setMarketBulkError('Selecione o país antes de validar.')
    if (!competition) return setMarketBulkError('Selecione o campeonato antes de validar.')

    // A validação estrutural acontece no navegador e aparece imediatamente.
    const quick=quickMarketBulkSummary(marketBulkRaw)
    if(!quick.total_rows)return setMarketBulkError('Nenhuma linha válida foi identificada. Verifique o formato da tabela.')
    setMarketBulkPreview({
      total_rows:quick.total_rows,
      seasons:quick.seasons,
      existing_rows:null,
      new_clubs_count:null,
      new_clubs:[],
      invalid_rows:[],
      checking_clubs:true,
    })

    // A conferência de clubes roda em segundo plano sem travar o botão/preview.
    api<any>('/api/market-values/bulk/preview', {
      method: 'POST',
      body: JSON.stringify({
        pais_id: country.id,
        campeonato_id: competition.id,
        moeda: currency,
        raw_text: marketBulkRaw,
      }),
    }).then(preview=>setMarketBulkPreview(preview)).catch(error=>{
      setMarketBulkError(error instanceof Error ? error.message : 'Não foi possível conferir os clubes no servidor.')
    })
  }

  async function importMarketBulk() {
    if (!country || !competition || !marketBulkRaw.trim()) return
    setMarketBulkError('')
    setMarketBulkLoading(true)
    try {
      const result = await api<any>('/api/market-values/bulk/import', {
        method: 'POST',
        body: JSON.stringify({
          pais_id: country.id,
          campeonato_id: competition.id,
          moeda: currency,
          raw_text: marketBulkRaw,
        }),
      })
      setMsg(
        `${Number(result.imported || 0).toLocaleString('pt-BR')} valores de mercado importados.` +
        (result.created_clubs ? ` ${Number(result.created_clubs).toLocaleString('pt-BR')} clube(s) novo(s) cadastrado(s).` : '')
      )
      setMarketBulkRaw('')
      setMarketBulkPreview(null)
      await Promise.all([loadGrid(1, gridSearch), Promise.resolve(loadClubs(country.id, competition.id, season, true)), loadMarketImports()])
      setGridPage(1)
    } catch (error) {
      setMarketBulkError(error instanceof Error ? error.message : 'Não foi possível importar os valores de mercado.')
    } finally {
      setMarketBulkLoading(false)
    }
  }

  async function saveCountry(e: React.FormEvent) {
    e.preventDefault()
    await api('/api/countries', {
      method: 'POST',
      body: JSON.stringify({ nome: countryName, continente: continent }),
    })
    setCountryName('')
    await refreshEverything()
    setMsg('País salvo.')
  }

  async function saveCompetition(e: React.FormEvent) {
    e.preventDefault()
    if (!country) return
    await api('/api/competitions', {
      method: 'POST',
      body: JSON.stringify({
        nome: competitionName,
        pais_id: country.id,
        principal,
      }),
    })
    setCompetitionName('')
    setPrincipal(false)
    setCompetitions(await api<Item[]>(`/api/competitions?country_id=${country.id}`))
    await loadGrid()
    setMsg('Campeonato salvo.')
  }

  async function saveClub(e: React.FormEvent) {
    e.preventDefault()
    if (!country) return
    await api('/api/clubs', {
      method: 'POST',
      body: JSON.stringify({
        nome: clubName,
        pais_id: country.id,
        campeonato_id: competition?.id || null,
        temporada: season || null,
        escudo_url: crest || null,
      }),
    })
    setClubName('')
    setCrest('')
    loadClubs()
    await loadGrid()
    setMsg('Clube salvo.')
  }

  async function openImportPreviousSeason() {
    if (!competition || !season.trim()) {
      setMsg('Selecione o campeonato e informe a temporada de destino antes de importar.')
      return
    }

    setImportLoading(true)
    try {
      const preview = await api<ImportPreview>(
        `/api/manage/clubs/import-preview?${query({
          campeonato_id: competition.id,
          temporada: season.trim(),
        })}`,
      )
      setImportPreview(preview)
      setImportSelected(new Set(preview.clubes.map(c => c.id)))
      setImportAdditional([{ key: 1, nome: '', clube_id: null }])
      setImportAdditionalKey(2)
    } catch (error) {
      setMsg(error instanceof Error ? error.message : 'Não foi possível carregar os clubes da temporada anterior.')
    } finally {
      setImportLoading(false)
    }
  }

  function toggleImportClub(clubId: number) {
    setImportSelected(current => {
      const next = new Set(current)
      if (next.has(clubId)) next.delete(clubId)
      else next.add(clubId)
      return next
    })
  }

  function toggleAllImportClubs() {
    if (!importPreview) return
    const allIds = importPreview.clubes.map(c => c.id)
    const allSelected = allIds.length > 0 && allIds.every(id => importSelected.has(id))
    setImportSelected(allSelected ? new Set() : new Set(allIds))
  }

  function addImportAdditionalClub() {
    setImportAdditional(current => {
      if (current.length >= 10) return current
      return [...current, { key: importAdditionalKey, nome: '', clube_id: null }]
    })
    setImportAdditionalKey(current => current + 1)
  }

  function updateImportAdditionalClub(value: ImportAdditionalClub) {
    setImportAdditional(current =>
      current.map(item => item.key === value.key ? value : item),
    )
  }

  function removeImportAdditionalClub(key: number) {
    setImportAdditional(current => current.filter(item => item.key !== key))
  }

  async function confirmImportPreviousSeason() {
    if (!importPreview || !competition) return
    setImportLoading(true)
    try {
      const result = await api<any>('/api/manage/clubs/import-previous-season', {
        method: 'POST',
        body: JSON.stringify({
          campeonato_id: competition.id,
          temporada: importPreview.temporada_destino,
          clube_ids: Array.from(importSelected),
          novos_clubes: importAdditional
            .filter(item => item.nome.trim())
            .map(item => ({ nome: item.nome.trim(), clube_id: item.clube_id })),
        }),
      })
      setImportPreview(null)
      setImportSelected(new Set())
      setImportAdditional([])
      setMsg(
        `${result.importados.toLocaleString('pt-BR')} clubes importados da temporada anterior.` +
        (result.novos_vinculos ? ` ${result.novos_vinculos.toLocaleString('pt-BR')} clube(s) adicional(is) vinculado(s).` : '') +
        (result.novos_cadastrados ? ` ${result.novos_cadastrados.toLocaleString('pt-BR')} cadastro(s) inédito(s) criado(s).` : '') +
        (result.ja_existentes || result.adicionais_ja_existentes
          ? ` ${(result.ja_existentes + result.adicionais_ja_existentes).toLocaleString('pt-BR')} já estavam na temporada destino.`
          : ''),
      )
      await Promise.all([loadGrid(1, gridSearch), Promise.resolve(loadClubs())])
      setGridPage(1)
    } catch (error) {
      setMsg(error instanceof Error ? error.message : 'Não foi possível importar os clubes.')
    } finally {
      setImportLoading(false)
    }
  }

  async function openEdit(row: AnyRow) {
    setEditing({ ...row })

    if (tab === 'clubes') {
      const detail = await api<any>(`/api/manage/clubs/${row.id}`)
      const clubCountryId = Number(detail?.pais_id ?? (row as ClubRow).pais_id)

      // O modal de edição usa uma lista própria de campeonatos.
      // Antes ele reutilizava `competitions`, que pertence ao formulário principal
      // da página e podia estar vazio quando o usuário abria o modal diretamente
      // pela tabela. Isso fazia o select exibir apenas "Campeonato...".
      const clubCompetitions = clubCountryId
        ? await api<Item[]>(`/api/competitions?country_id=${clubCountryId}`)
        : []

      setEditCompetitions(clubCompetitions)
      setClubDetail(detail)
      setEditing({ ...row, ...detail })
    } else {
      setClubDetail(null)
    }

    if (tab === 'valor') {
      const r = row as MarketRow
      setEditCompetitions(await api<Item[]>(`/api/competitions?country_id=${r.pais_id}`))
      setEditClubs(await api<Item[]>(`/api/clubs?country_id=${r.pais_id}`))
    } else if (tab === 'campeonatos' || tab === 'paises') {
      setEditCompetitions([])
    }
  }

  async function deleteRow(row: AnyRow) {
    const labels: Record<Tab, string> = {
      valor: 'valor de mercado',
      clubes: 'clube',
      campeonatos: 'campeonato',
      paises: 'país',
    }
    if (!window.confirm(`Excluir este ${labels[tab]}? Os vínculos dependentes também poderão ser removidos.`)) {
      return
    }

    const path =
      tab === 'valor'
        ? `/api/manage/market-values/${row.id}`
        : tab === 'clubes'
          ? `/api/manage/clubs/${row.id}`
          : tab === 'campeonatos'
            ? `/api/manage/competitions/${row.id}`
            : `/api/manage/countries/${row.id}`

    await api(path, { method: 'DELETE' })
    setMsg('Registro excluído.')
    if (gridRows.length === 1 && gridPage > 1) setGridPage(p => p - 1)
    else await refreshEverything()
  }

  async function saveEdit(e: React.FormEvent) {
    e.preventDefault()
    if (!editing) return

    if (tab === 'paises') {
      const r = editing as CountryRow
      await api(`/api/manage/countries/${r.id}`, {
        method: 'PUT',
        body: JSON.stringify({ nome: r.nome, continente: r.continente }),
      })
    }

    if (tab === 'campeonatos') {
      const r = editing as CompetitionRow
      await api(`/api/manage/competitions/${r.id}`, {
        method: 'PUT',
        body: JSON.stringify({
          nome: r.nome,
          pais_id: Number(r.pais_id),
          principal: Boolean(r.principal),
        }),
      })
    }

    if (tab === 'clubes') {
      const r = editing as ClubRow
      await api(`/api/manage/clubs/${r.id}`, {
        method: 'PUT',
        body: JSON.stringify({
          nome: r.nome,
          pais_id: Number(r.pais_id),
          escudo_url: r.escudo_url || null,
        }),
      })
    }

    if (tab === 'valor') {
      const r = editing as MarketRow
      await api(`/api/manage/market-values/${r.id}`, {
        method: 'PUT',
        body: JSON.stringify({
          temporada: r.temporada,
          pais_id: Number(r.pais_id),
          campeonato_id: Number(r.campeonato_id),
          clube_id: Number(r.clube_id),
          valor: Number(r.valor),
          moeda: r.moeda,
        }),
      })
    }

    setEditing(null)
    setClubDetail(null)
    setMsg('Registro atualizado.')
    await refreshEverything()
  }

  async function updateMarketCountry(paisId: number) {
    if (!editing || tab !== 'valor') return
    const comps = await api<Item[]>(`/api/competitions?country_id=${paisId}`)
    const cls = await api<Item[]>(`/api/clubs?country_id=${paisId}`)
    setEditCompetitions(comps)
    setEditClubs(cls)
    setEditing({
      ...(editing as MarketRow),
      pais_id: paisId,
      campeonato_id: 0,
      clube_id: 0,
    })
  }

  async function addMembership() {
    if (!editing || tab !== 'clubes') return

    const competitionSelect = document.getElementById('membership-comp') as HTMLSelectElement | null
    const seasonInput = document.getElementById('membership-season') as HTMLInputElement | null
    const comp = Number(competitionSelect?.value)
    const seasonValue = seasonInput?.value.trim() || ''

    if (!comp) {
      setMsg('Selecione o campeonato antes de adicionar o vínculo.')
      return
    }

    if (!seasonValue) {
      setMsg('Informe a temporada antes de adicionar o vínculo.')
      return
    }

    await api(`/api/manage/clubs/${editing.id}/memberships`, {
      method: 'POST',
      body: JSON.stringify({ campeonato_id: comp, temporada: seasonValue }),
    })

    const detail = await api<any>(`/api/manage/clubs/${editing.id}`)
    setClubDetail(detail)

    if (competitionSelect) competitionSelect.value = ''
    if (seasonInput) seasonInput.value = ''
    setMsg('Vínculo de temporada/campeonato adicionado.')
    await loadGrid(gridPage, gridSearch)
  }

  async function removeMembership(campeonato_id: number, temporada: string) {
    if (!editing || tab !== 'clubes') return
    await api(
      `/api/manage/clubs/${editing.id}/memberships?${query({ campeonato_id, temporada })}`,
      { method: 'DELETE' },
    )
    const detail = await api<any>(`/api/manage/clubs/${editing.id}`)
    setClubDetail(detail)
  }

  const marketColumns: CrudColumn<any>[] = [
    { key: 'temporada', label: 'Temporada' },
    { key: 'pais', label: 'País' },
    { key: 'campeonato', label: 'Campeonato' },
    {
      key: 'clube',
      label: 'Clube',
      render: r => (
        <div className="club-inline">
          {r.escudo_url ? <img src={r.escudo_url} /> : <span className="mini-crest">{r.clube?.[0]}</span>}
          <strong>{r.clube}</strong>
        </div>
      ),
    },
    { key: 'valor', label: 'Valor', render: r => money(r.valor, r.moeda), className: 'numeric' },
    { key: 'moeda', label: 'Moeda' },
    {
      key: 'atualizado_em',
      label: 'Atualização',
      render: r => r.atualizado_em ? new Date(r.atualizado_em).toLocaleString('pt-BR') : '—',
    },
  ]

  const clubColumns: CrudColumn<any>[] = [
    {
      key: 'nome',
      label: 'Clube',
      render: r => (
        <div className="club-inline">
          {r.escudo_url ? <img src={r.escudo_url} /> : <span className="mini-crest">{r.nome?.[0]}</span>}
          <strong>{r.nome}</strong>
        </div>
      ),
    },
    { key: 'pais', label: 'País' },
    { key: 'vinculos', label: 'Temporadas / Campeonatos' },
    { key: 'escudo_url', label: 'Escudo', render: r => r.escudo_url || '—' },
  ]

  const competitionColumns: CrudColumn<any>[] = [
    { key: 'nome', label: 'Campeonato' },
    { key: 'pais', label: 'País' },
    {
      key: 'principal',
      label: 'Principal',
      render: r => r.principal ? <span className="tag blue">Principal</span> : '—',
    },
  ]

  const countryColumns: CrudColumn<any>[] = [
    { key: 'nome', label: 'País' },
    { key: 'continente', label: 'Continente' },
  ]

  const gridConfig = {
    valor: { title: 'Valores de mercado', columns: marketColumns },
    clubes: { title: 'Clubes cadastrados', columns: clubColumns },
    campeonatos: { title: 'Campeonatos cadastrados', columns: competitionColumns },
    paises: { title: 'Países cadastrados', columns: countryColumns },
  }[tab]

  const editCountryCompetitions = editing && 'pais_id' in editing
    ? competitions.filter(c => c.pais_id === Number((editing as any).pais_id))
    : []

  const importPreviousSeasonIds = useMemo(
    () => importPreview ? importPreview.clubes.map(c => c.id) : [],
    [importPreview],
  )

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <span className="eyebrow">CONFIGURAÇÃO</span>
          <h1>Cadastros</h1>
          <p>Base oficial de clubes, campeonatos e valores de mercado.</p>
        </div>
      </div>

      <div className="subtabs">
        <button className={tab === 'valor' ? 'active' : ''} onClick={() => changeTab('valor')}>Valor de Mercado</button>
        <button className={tab === 'clubes' ? 'active' : ''} onClick={() => changeTab('clubes')}>Clubes</button>
        <button className={tab === 'campeonatos' ? 'active' : ''} onClick={() => changeTab('campeonatos')}>Campeonatos</button>
        <button className={tab === 'paises' ? 'active' : ''} onClick={() => changeTab('paises')}>Países</button>
      </div>

      {msg && <div className="notice success">{msg}</div>}

      {tab === 'valor' && (
        <>
          <form className="panel form-grid four" onSubmit={saveMarket}>
            <div className="field"><label>Temporada *</label><input value={season} onChange={e => setSeason(e.target.value)} placeholder="2015/2016" /></div>
            <IdAutocomplete label="País" value={country} options={countries} onChange={setCountry} required />
            <IdAutocomplete label="Campeonato" value={competition} options={competitions} onChange={setCompetition} disabled={!country} required />
            <IdAutocomplete label="Clube" value={club} options={clubs} onChange={setClub} disabled={!country || !competition || !season} required />
            <div className="field"><label>Valor de mercado *</label><input value={value} onChange={e => setValue(e.target.value)} placeholder="562550000" /></div>
            <div className="field"><label>Moeda *</label><select value={currency} onChange={e => setCurrency(e.target.value)}><option value="EUR">Euro (€)</option><option value="USD">Dólar (US$)</option><option value="BRL">Real (R$)</option></select></div>
            <div className="form-actions"><button className="primary">Salvar valor</button></div>
          </form>

          <div className="panel pad market-bulk-panel">
            <div className="panel-title">
              <div>
                <h2>Colar valores de mercado</h2>
                <span>Use o país, campeonato e moeda selecionados acima. A temporada vem de cada linha colada.</span>
              </div>
            </div>
            <p className="muted">Formato: Temporada | Clube | Valor de mercado | Escudo. Se o clube ainda não existir, ele será cadastrado automaticamente e vinculado à temporada.</p>
            <textarea
              className="paste-area market-paste-area"
              value={marketBulkRaw}
              onChange={e => { setMarketBulkRaw(e.target.value); setMarketBulkPreview(null); setMarketBulkError('') }}
              placeholder={'| Temporada | Clube | Valor de mercado | Escudo |\n| --- | --- | --- | --- |\n| 2010/2011 | Bayern de Munique | 308.980.000 | https://img.a.transfermarkt.technology/wappen/head/27.png |'}
            />
            <div className="bulk-actions">
              <button type="button" className="primary" onClick={previewMarketBulk} disabled={!marketBulkRaw.trim() || marketBulkLoading}>
                {marketBulkLoading ? 'Validando...' : 'Validar dados'}
              </button>
              {marketBulkPreview && (
                <button type="button" className="primary" onClick={importMarketBulk} disabled={marketBulkLoading}>
                  Importar {Number(marketBulkPreview.total_rows || 0).toLocaleString('pt-BR')} valores
                </button>
              )}
            </div>
            {marketBulkError && <div className="notice error compact">{marketBulkError}</div>}
            {marketBulkPreview && (
              <div className="market-bulk-preview">
                <div className="import-summary">
                  <span><strong>{Number(marketBulkPreview.total_rows || 0).toLocaleString('pt-BR')}</strong> valores</span>
                  <span><strong>{Number(marketBulkPreview.seasons?.length || 0).toLocaleString('pt-BR')}</strong> temporadas</span>
                  <span><strong>{marketBulkPreview.existing_rows==null?'…':Number(marketBulkPreview.existing_rows).toLocaleString('pt-BR')}</strong> linhas com clube existente</span>
                  <span><strong>{marketBulkPreview.new_clubs_count==null?'…':Number(marketBulkPreview.new_clubs_count).toLocaleString('pt-BR')}</strong> clubes novos</span>
                </div>
                {marketBulkPreview.checking_clubs && <div className="notice info compact">Estrutura validada. Conferindo clubes cadastrados em segundo plano…</div>}
                {marketBulkPreview.new_clubs?.length > 0 && (
                  <div className="bulk-new-clubs">
                    <strong>Clubes que serão cadastrados:</strong>
                    <span>{marketBulkPreview.new_clubs.join(' · ')}</span>
                  </div>
                )}
                {marketBulkPreview.invalid_rows?.length > 0 && (
                  <div className="notice info compact">
                    {marketBulkPreview.invalid_rows.length.toLocaleString('pt-BR')} linha(s) inválida(s) serão ignoradas.
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="panel section-space market-import-history">
            <div className="panel-title">
              <div>
                <h2>Últimas cargas de valor de mercado</h2>
                <span>10 cargas mais recentes. Cargas excluídas permanecem no histórico para auditoria.</span>
              </div>
              <button type="button" className="secondary" onClick={loadMarketImports} disabled={marketImportsLoading}>{marketImportsLoading?'Atualizando...':'Atualizar'}</button>
            </div>
            <div className="table-scroll"><table><thead><tr><th>Carga</th><th>Data</th><th>País</th><th>Campeonato</th><th>Temporadas</th><th>Moeda</th><th>Valores</th><th>Ativos</th><th>Status</th><th>Ação</th></tr></thead><tbody>
              {marketImports.map((r:any)=><tr key={r.id}><td><strong>#{r.id}</strong></td><td>{r.criado_em?new Date(r.criado_em).toLocaleString('pt-BR'):'—'}</td><td>{r.pais}</td><td>{r.campeonato}</td><td>{r.temporadas||'—'}</td><td>{r.moeda}</td><td>{Number(r.linhas_importadas||0).toLocaleString('pt-BR')}</td><td>{Number(r.linhas_ativas||0).toLocaleString('pt-BR')}</td><td>{r.excluido_em?<span className="tag deleted">Excluída</span>:<span className="tag active">Ativa</span>}</td><td>{r.excluido_em?'—':<button type="button" className="action-delete" onClick={()=>deleteMarketImport(r.id)}>Excluir</button>}</td></tr>)}
            </tbody></table></div>
            {!marketImports.length&&!marketImportsLoading&&<div className="empty-state compact">Ainda não há cargas registradas.</div>}
          </div>
        </>
      )}

      {tab === 'campeonatos' && (
        <div className="panel">
          <form className="form-grid four" onSubmit={saveCompetition}>
            <IdAutocomplete label="País" value={country} options={countries} onChange={setCountry} required />
            <div className="field"><label>Campeonato *</label><input value={competitionName} onChange={e => setCompetitionName(e.target.value)} required /></div>
            <label className="check-field"><input type="checkbox" checked={principal} onChange={e => setPrincipal(e.target.checked)} /><span><strong>Campeonato principal</strong><small>Usado como padrão nas análises do país.</small></span></label>
            <div className="form-actions"><button className="primary">Salvar campeonato</button></div>
          </form>
        </div>
      )}

      {tab === 'clubes' && (
        <div className="panel">
          <form className="form-grid four" onSubmit={saveClub}>
            <div className="field"><label>Temporada</label><input value={season} onChange={e => setSeason(e.target.value)} placeholder="2015/2016" /></div>
            <IdAutocomplete label="País" value={country} options={countries} onChange={setCountry} required />
            <IdAutocomplete label="Campeonato" value={competition} options={competitions} onChange={setCompetition} disabled={!country} />
            <div className="field"><label>Clube *</label><input value={clubName} onChange={e => setClubName(e.target.value)} required /></div>
            <div className="field span-2"><label>Link do escudo</label><input value={crest} onChange={e => setCrest(e.target.value)} placeholder="https://img.a.transfermarkt.technology/wappen/head/27.png?..." /></div>
            <div className="form-actions club-form-actions">
              <button className="primary">Salvar clube</button>
              <button
                type="button"
                className="secondary import-season-button"
                onClick={openImportPreviousSeason}
                disabled={!competition || !season.trim() || importLoading}
              >
                {importLoading ? 'Carregando...' : 'Importar temporada anterior'}
              </button>
            </div>
          </form>
        </div>
      )}

      {tab === 'paises' && (
        <div className="panel">
          <form className="form-grid four" onSubmit={saveCountry}>
            <div className="field"><label>País *</label><input value={countryName} onChange={e => setCountryName(e.target.value)} required /></div>
            <div className="field"><label>Continente *</label><select value={continent} onChange={e => setContinent(e.target.value)}><option>Europa</option><option>Ásia</option><option>América do Sul</option><option>América do Norte</option><option>Oceania</option></select></div>
            <div className="form-actions"><button className="primary">Salvar país</button></div>
          </form>
        </div>
      )}

      {tab === 'clubes' && (
        <div className="panel club-grid-filters">
          <div className="club-grid-filter-head">
            <div>
              <span className="eyebrow">FILTROS DOS CLUBES CADASTRADOS</span>
              <strong>Refine a listagem</strong>
            </div>
            <button
              type="button"
              className="secondary"
              onClick={() => {
                setClubFilterSeason('')
                setClubFilterCountry(null)
                setClubFilterCompetition(null)
                setGridPage(1)
              }}
            >
              Limpar filtros
            </button>
          </div>

          <div className="club-grid-filter-fields">
            <div className="field">
              <label>Temporada</label>
              <input
                value={clubFilterSeason}
                onChange={e => {
                  setClubFilterSeason(e.target.value)
                  setGridPage(1)
                }}
                placeholder="Ex.: 2016/2017"
              />
            </div>

            <IdAutocomplete
              label="País"
              value={clubFilterCountry}
              options={countries}
              onChange={value => {
                setClubFilterCountry(value)
                setGridPage(1)
              }}
            />

            <IdAutocomplete
              label="Campeonato"
              value={clubFilterCompetition}
              options={clubFilterCompetitions}
              onChange={value => {
                setClubFilterCompetition(value)
                setGridPage(1)
              }}
              disabled={!clubFilterCountry}
            />
          </div>
        </div>
      )}

      <CrudDataFrame
        title={gridConfig.title}
        rows={gridRows as any[]}
        columns={gridConfig.columns}
        total={gridTotal}
        page={gridPage}
        pageSize={PAGE_SIZE}
        search={gridSearch}
        loading={gridLoading}
        onSearch={value => { setGridSearch(value); setGridPage(1) }}
        onPage={setGridPage}
        onEdit={openEdit}
        onDelete={deleteRow}
      />

      {importPreview && (
        <Modal
          title={`Importar clubes de ${importPreview.temporada_origem}`}
          onClose={() => { setImportPreview(null); setImportSelected(new Set()); setImportAdditional([]) }}
        >
          <div className="import-season-summary">
            <div>
              <small>Campeonato</small>
              <strong>{importPreview.campeonato?.nome || competition?.nome || '—'}</strong>
            </div>
            <span>→</span>
            <div>
              <small>Temporada destino</small>
              <strong>{importPreview.temporada_destino}</strong>
            </div>
          </div>

          <div className="import-section-title">
            <div>
              <strong>Clubes da temporada anterior</strong>
              <small>Todos vêm selecionados por padrão. Desmarque quem não deve seguir para a temporada destino.</small>
            </div>
          </div>

          {importPreview.clubes.length ? (
            <div className="import-season-table-wrap">
              <table className="import-season-table">
                <thead>
                  <tr>
                    <th className="import-check-col">
                      <input
                        type="checkbox"
                        checked={importPreview.clubes.every(c => importSelected.has(c.id))}
                        onChange={toggleAllImportClubs}
                        title="Selecionar todos"
                      />
                    </th>
                    <th>Clube</th>
                    <th>País</th>
                    <th>Status na temporada destino</th>
                  </tr>
                </thead>
                <tbody>
                  {importPreview.clubes.map(c => (
                    <tr key={c.id}>
                      <td className="import-check-col">
                        <input
                          type="checkbox"
                          checked={importSelected.has(c.id)}
                          onChange={() => toggleImportClub(c.id)}
                        />
                      </td>
                      <td>
                        <div className="club-inline">
                          {c.escudo_url ? <img src={c.escudo_url} alt="" /> : <span className="mini-crest">{c.nome[0]}</span>}
                          <strong>{c.nome}</strong>
                        </div>
                      </td>
                      <td>{c.pais}</td>
                      <td>
                        {c.ja_cadastrado
                          ? <span className="import-status existing">Já cadastrado</span>
                          : <span className="import-status new">Será importado</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="import-season-empty compact">
              Nenhum clube foi encontrado em <strong>{importPreview.temporada_origem}</strong> para este campeonato.
            </div>
          )}

          <div className="additional-clubs-section">
            <div className="additional-clubs-head">
              <div>
                <strong>Adicionar clubes novos / promovidos</strong>
                <small>
                  A lista suspensa reúne todos os clubes únicos já cadastrados neste campeonato, em qualquer temporada. Dela removemos somente os clubes exibidos acima em "Clubes da temporada anterior".
                  Você também pode digitar para filtrar. Se o clube não existir no campeonato, criamos somente o nome e você completa depois.
                </small>
              </div>
              <button
                type="button"
                className="secondary"
                onClick={addImportAdditionalClub}
                disabled={importAdditional.length >= 10}
              >
                + Adicionar clube ({importAdditional.length}/10)
              </button>
            </div>

            <div className="additional-clubs-list">
              {importAdditional.map(item => (
                <CompetitionClubLookup
                  key={item.key}
                  value={item}
                  competitionId={competition?.id || 0}
                  season={importPreview.temporada_destino}
                  excludedClubIds={importPreviousSeasonIds}
                  onChange={updateImportAdditionalClub}
                  onRemove={() => removeImportAdditionalClub(item.key)}
                />
              ))}
              {!importAdditional.length && (
                <button type="button" className="additional-club-first" onClick={addImportAdditionalClub}>
                  + Adicionar um clube que não veio da temporada anterior
                </button>
              )}
            </div>
          </div>

          <div className="import-season-footer">
            <span>
              <strong>{importSelected.size}</strong> de {importPreview.clubes.length} clubes anteriores selecionados
              {' · '}
              <strong>{importAdditional.filter(x => x.nome.trim()).length}</strong> adicionais preenchidos
            </span>
            <div>
              <button
                type="button"
                className="secondary"
                onClick={() => { setImportPreview(null); setImportSelected(new Set()); setImportAdditional([]) }}
              >
                Cancelar
              </button>
              <button
                type="button"
                className="primary"
                disabled={
                  (!importSelected.size && !importAdditional.some(x => x.nome.trim())) ||
                  importLoading
                }
                onClick={confirmImportPreviousSeason}
              >
                {importLoading
                  ? 'Importando...'
                  : `Confirmar importação (${importSelected.size + importAdditional.filter(x => x.nome.trim()).length})`}
              </button>
            </div>
          </div>
        </Modal>
      )}

      {editing && (
        <Modal title="Editar cadastro" onClose={() => { setEditing(null); setClubDetail(null) }}>
          <form className="modal-form" onSubmit={saveEdit}>
            {tab === 'paises' && (() => {
              const r = editing as CountryRow
              return <>
                <div className="field"><label>País</label><input value={r.nome} onChange={e => setEditing({ ...r, nome: e.target.value })} /></div>
                <div className="field"><label>Continente</label><select value={r.continente} onChange={e => setEditing({ ...r, continente: e.target.value })}><option>Europa</option><option>Ásia</option><option>América do Sul</option><option>América do Norte</option><option>Oceania</option></select></div>
              </>
            })()}

            {tab === 'campeonatos' && (() => {
              const r = editing as CompetitionRow
              return <>
                <div className="field"><label>Campeonato</label><input value={r.nome} onChange={e => setEditing({ ...r, nome: e.target.value })} /></div>
                <div className="field"><label>País</label><select value={r.pais_id} onChange={e => setEditing({ ...r, pais_id: Number(e.target.value) })}>{countries.map(c => <option key={c.id} value={c.id}>{c.nome}</option>)}</select></div>
                <label className="check-field modal-check"><input type="checkbox" checked={r.principal} onChange={e => setEditing({ ...r, principal: e.target.checked })} /><span><strong>Campeonato principal</strong></span></label>
              </>
            })()}

            {tab === 'clubes' && (() => {
              const r = editing as ClubRow
              const compsForClub = editCompetitions
              return <>
                <div className="field"><label>Clube</label><input value={r.nome} onChange={e => setEditing({ ...r, nome: e.target.value })} /></div>
                <div className="field"><label>País</label><select value={r.pais_id} onChange={async e => {
                  const newCountry = Number(e.target.value)
                  setEditing({ ...r, pais_id: newCountry })
                  setEditCompetitions(await api<Item[]>(`/api/competitions?country_id=${newCountry}`))
                }}>{countries.map(c => <option key={c.id} value={c.id}>{c.nome}</option>)}</select></div>
                <div className="field"><label>Link do escudo</label><input value={r.escudo_url || ''} onChange={e => setEditing({ ...r, escudo_url: e.target.value })} /></div>

                <div className="membership-editor">
                  <label>Vínculos de temporada / campeonato</label>
                  {(clubDetail?.vinculos || []).map((v: any) => (
                    <div className="membership-row" key={`${v.campeonato_id}-${v.temporada}`}>
                      <span>{v.temporada} · {v.campeonato}</span>
                      <button type="button" onClick={() => removeMembership(v.campeonato_id, v.temporada)}>Remover</button>
                    </div>
                  ))}
                  <div className="membership-add">
                    <select id="membership-comp">
                      <option value="">Campeonato...</option>
                      {compsForClub.map(c => <option key={c.id} value={c.id}>{c.nome}</option>)}
                    </select>
                    <input id="membership-season" placeholder="Temporada" />
                    <button type="button" onClick={addMembership}>Adicionar vínculo</button>
                  </div>
                </div>
              </>
            })()}

            {tab === 'valor' && (() => {
              const r = editing as MarketRow
              return <>
                <div className="field"><label>Temporada</label><input value={r.temporada} onChange={e => setEditing({ ...r, temporada: e.target.value })} /></div>
                <div className="field"><label>País</label><select value={r.pais_id} onChange={e => updateMarketCountry(Number(e.target.value))}>{countries.map(c => <option key={c.id} value={c.id}>{c.nome}</option>)}</select></div>
                <div className="field"><label>Campeonato</label><select value={r.campeonato_id} onChange={e => setEditing({ ...r, campeonato_id: Number(e.target.value) })}><option value={0}>Selecione...</option>{editCompetitions.map(c => <option key={c.id} value={c.id}>{c.nome}</option>)}</select></div>
                <div className="field"><label>Clube</label><select value={r.clube_id} onChange={e => setEditing({ ...r, clube_id: Number(e.target.value) })}><option value={0}>Selecione...</option>{editClubs.map(c => <option key={c.id} value={c.id}>{c.nome}</option>)}</select></div>
                <div className="field"><label>Valor</label><input type="number" min="0" value={r.valor} onChange={e => setEditing({ ...r, valor: Number(e.target.value) })} /></div>
                <div className="field"><label>Moeda</label><select value={r.moeda} onChange={e => setEditing({ ...r, moeda: e.target.value })}><option value="EUR">EUR</option><option value="USD">USD</option><option value="BRL">BRL</option></select></div>
              </>
            })()}

            <div className="modal-actions">
              <button type="button" className="secondary" onClick={() => { setEditing(null); setClubDetail(null) }}>Cancelar</button>
              <button className="primary">Salvar alterações</button>
            </div>
          </form>
        </Modal>
      )}
    </section>
  )
}
