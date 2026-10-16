import React from 'react'

export type CrudColumn<T> = {
  key: string
  label: string
  render?: (row: T) => React.ReactNode
  className?: string
}

type Props<T> = {
  title: string
  rows: T[]
  columns: CrudColumn<T>[]
  total: number
  page: number
  pageSize?: number
  search: string
  loading?: boolean
  onSearch: (value: string) => void
  onPage: (page: number) => void
  onEdit: (row: T) => void
  onDelete: (row: T) => void
}

export default function CrudDataFrame<T extends { id: number }>({
  title,
  rows,
  columns,
  total,
  page,
  pageSize = 20,
  search,
  loading,
  onSearch,
  onPage,
  onEdit,
  onDelete,
}: Props<T>) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  const start = total ? (page - 1) * pageSize + 1 : 0
  const end = Math.min(page * pageSize, total)

  return (
    <div className="panel section-space crud-frame">
      <div className="crud-toolbar">
        <div>
          <span className="eyebrow">DADOS CADASTRADOS</span>
          <h2>{title}</h2>
          <small>{total.toLocaleString('pt-BR')} registros</small>
        </div>

        <div className="crud-search">
          <span>⌕</span>
          <input
            value={search}
            onChange={e => onSearch(e.target.value)}
            placeholder="Buscar qualquer informação..."
          />
        </div>
      </div>

      <div className="table-scroll">
        <table className="crud-table">
          <thead>
            <tr>
              {columns.map(col => <th key={col.key}>{col.label}</th>)}
              <th className="actions-col">Ações</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={columns.length + 1} className="crud-empty">Carregando...</td></tr>
            ) : rows.length ? (
              rows.map(row => (
                <tr key={row.id}>
                  {columns.map(col => (
                    <td key={col.key} className={col.className || ''}>
                      {col.render ? col.render(row) : String((row as any)[col.key] ?? '—')}
                    </td>
                  ))}
                  <td className="crud-actions">
                    <button className="action-edit" onClick={() => onEdit(row)}>Editar</button>
                    <button className="action-delete" onClick={() => onDelete(row)}>Excluir</button>
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={columns.length + 1} className="crud-empty">
                  Nenhum registro encontrado.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="crud-pagination">
        <span>{start.toLocaleString('pt-BR')}–{end.toLocaleString('pt-BR')} de {total.toLocaleString('pt-BR')}</span>
        <div>
          <button disabled={page <= 1} onClick={() => onPage(page - 1)}>←</button>
          <strong>{page} / {pages}</strong>
          <button disabled={page >= pages} onClick={() => onPage(page + 1)}>→</button>
        </div>
      </div>
    </div>
  )
}
