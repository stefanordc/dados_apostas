import { useEffect, useMemo, useRef, useState } from 'react'

type Props = {
  label: string
  value: string
  options: string[]
  onChange: (value: string) => void
  placeholder?: string
  required?: boolean
  disabled?: boolean
}

export default function Autocomplete({
  label, value, options, onChange, placeholder, required, disabled
}: Props) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler = (ev: MouseEvent) => {
      if (box.current && !box.current.contains(ev.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const filtered = useMemo(() => {
    const term = value.trim().toLocaleLowerCase('pt-BR')
    if (!term) return options.slice(0, 100)
    return options
      .filter(x => x.toLocaleLowerCase('pt-BR').includes(term))
      .slice(0, 100)
  }, [value, options])

  return (
    <div className="field autocomplete" ref={box}>
      <label>{label}{required && <span className="required"> *</span>}</label>
      <input
        value={value}
        disabled={disabled}
        placeholder={placeholder || `Digite ${label.toLowerCase()}...`}
        onFocus={() => setOpen(true)}
        onChange={e => { onChange(e.target.value); setOpen(true) }}
      />
      {open && !disabled && (
        <div className="autocomplete-menu">
          {filtered.length === 0 ? (
            <div className="autocomplete-empty">Nenhuma opção</div>
          ) : filtered.map(option => (
            <button
              type="button"
              key={option}
              onMouseDown={e => e.preventDefault()}
              onClick={() => { onChange(option); setOpen(false) }}
            >
              {option}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
