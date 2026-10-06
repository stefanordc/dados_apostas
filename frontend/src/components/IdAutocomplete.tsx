import { useEffect, useMemo, useRef, useState } from 'react'

type Item = { id: number; nome: string; [key: string]: unknown }

type Props = {
  label: string
  value: Item | null
  options: Item[]
  onChange: (item: Item | null) => void
  required?: boolean
  disabled?: boolean
  placeholder?: string
}

export default function IdAutocomplete({
  label,
  value,
  options,
  onChange,
  required,
  disabled,
  placeholder,
}: Props) {
  const [text, setText] = useState('')
  const [open, setOpen] = useState(false)
  const [activeIndex, setActiveIndex] = useState(-1)
  const inputRef = useRef<HTMLInputElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)

  const display = value ? value.nome : text

  const filtered = useMemo(() => {
    // Se já existe um item selecionado, ArrowDown deve permitir navegar pela lista inteira.
    const term = value ? '' : text.trim().toLocaleLowerCase('pt-BR')
    const base = term
      ? options.filter(item => item.nome.toLocaleLowerCase('pt-BR').includes(term))
      : options

    return base.slice(0, 150)
  }, [text, value, options])

  useEffect(() => {
    setActiveIndex(-1)
  }, [text, options, value?.id])

  useEffect(() => {
    if (!open || activeIndex < 0 || !menuRef.current) return
    const el = menuRef.current.querySelector<HTMLElement>(`[data-option-index="${activeIndex}"]`)
    el?.scrollIntoView({ block: 'nearest' })
  }, [activeIndex, open])

  function selectItem(item: Item) {
    onChange(item)
    setText('')
    setOpen(false)
    setActiveIndex(-1)
    requestAnimationFrame(() => inputRef.current?.focus())
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (disabled) return

    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setOpen(true)
      setActiveIndex(prev => {
        if (!filtered.length) return -1
        return prev < filtered.length - 1 ? prev + 1 : 0
      })
      return
    }

    if (e.key === 'ArrowUp') {
      e.preventDefault()
      setOpen(true)
      setActiveIndex(prev => {
        if (!filtered.length) return -1
        return prev > 0 ? prev - 1 : filtered.length - 1
      })
      return
    }

    if (e.key === 'Enter' && open && activeIndex >= 0 && filtered[activeIndex]) {
      e.preventDefault()
      selectItem(filtered[activeIndex])
      return
    }

    if (e.key === 'Escape') {
      setOpen(false)
      setActiveIndex(-1)
    }
  }

  return (
    <div className="field autocomplete">
      <label>
        {label}
        {required && <span className="required"> *</span>}
      </label>

      <div className={`autocomplete-input-shell ${open ? 'is-open' : ''}`}>
        <input
          ref={inputRef}
          disabled={disabled}
          value={display}
          autoComplete="off"
          placeholder={placeholder || `Buscar ${label.toLowerCase()}...`}
          onFocus={() => setOpen(true)}
          onBlur={() => {
            window.setTimeout(() => {
              setOpen(false)
              setActiveIndex(-1)
            }, 140)
          }}
          onKeyDown={handleKeyDown}
          onChange={e => {
            setText(e.target.value)
            onChange(null)
            setOpen(true)
          }}
        />
        <span className="autocomplete-chevron" aria-hidden="true">⌄</span>
      </div>

      {open && !disabled && (
        <div className="autocomplete-menu" ref={menuRef}>
          {filtered.length ? (
            filtered.map((item, index) => (
              <button
                key={item.id}
                type="button"
                data-option-index={index}
                className={index === activeIndex ? 'active' : ''}
                onMouseEnter={() => setActiveIndex(index)}
                onMouseDown={e => {
                  // Seleciona antes do blur do input. Corrige o clique que não fixava o clube.
                  e.preventDefault()
                  selectItem(item)
                }}
              >
                <span>{item.nome}</span>
                {value?.id === item.id && <span className="option-check">✓</span>}
              </button>
            ))
          ) : (
            <div className="autocomplete-empty">Nenhuma opção encontrada</div>
          )}
        </div>
      )}
    </div>
  )
}
