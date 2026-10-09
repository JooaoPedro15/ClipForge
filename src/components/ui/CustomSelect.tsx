import { Check, ChevronDown } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { cn } from '@/lib/utils'

interface SelectOption {
  value: string
  label: string
  hint?: string
}

interface CustomSelectProps {
  value: string
  onChange: (value: string) => void
  options: SelectOption[]
  className?: string
  id?: string
}

export function CustomSelect({ value, onChange, options, className, id }: CustomSelectProps) {
  // Controla a abertura do dropdown e referencia o container para clique externo.
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  // Recupera a opcao selecionada para mostrar o label amigavel no botao.
  const selected = options.find((o) => o.value === value)

  useEffect(() => {
    if (!open) {
      return
    }

    // Fecha o menu no clique fora ou no Esc, como um select nativo.
    function handleClickOutside(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    function handleKey(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setOpen(false)
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    document.addEventListener('keydown', handleKey)
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('keydown', handleKey)
    }
  }, [open])

  return (
    <div ref={ref} className={cn('relative', className)}>
      <button
        aria-expanded={open}
        aria-haspopup="listbox"
        className="app-no-drag flex h-9 w-full items-center justify-between gap-2 rounded-md border border-line bg-raised px-3 text-left text-sm text-text-primary transition-colors hover:border-line-strong"
        id={id}
        onClick={() => setOpen(!open)}
        type="button"
      >
        <span className="truncate">{selected?.label ?? value}</span>
        <ChevronDown className={cn('h-4 w-4 shrink-0 text-text-muted transition-transform', open && 'rotate-180')} />
      </button>

      {open && (
        <div
          className="absolute z-50 mt-1 w-full overflow-hidden rounded-lg border border-line-strong bg-raised py-1 shadow-[0_12px_32px_rgba(0,0,0,0.5)]"
          role="listbox"
        >
          {options.map((option) => {
            const isSelected = option.value === value
            return (
              <button
                aria-selected={isSelected}
                className={cn(
                  'flex w-full items-start gap-2 px-3 py-2 text-left text-sm transition-colors',
                  isSelected ? 'text-text-primary' : 'text-text-secondary hover:bg-white/5 hover:text-text-primary',
                )}
                key={option.value}
                onClick={() => {
                  onChange(option.value)
                  setOpen(false)
                }}
                role="option"
                type="button"
              >
                <Check className={cn('mt-0.5 h-3.5 w-3.5 shrink-0', isSelected ? 'opacity-100' : 'opacity-0')} />
                <span>
                  <span className="block">{option.label}</span>
                  {option.hint ? <span className="block text-xs text-text-muted">{option.hint}</span> : null}
                </span>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
