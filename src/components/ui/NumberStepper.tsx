import { Minus, Plus } from 'lucide-react'
import { useState } from 'react'

interface NumberStepperProps {
  value: number
  onChange: (value: number) => void
  label: string
  min?: number
  max?: number
  step?: number
  // Texto mostrado quando o valor e 0 (ex.: "auto" pra "sem limite").
  zeroLabel?: string
  id?: string
}

// Arredonda pela casa decimal do passo pra 0.1 + 0.2 nao virar 0.30000000000000004.
function roundToStep(value: number, step: number): number {
  const decimals = (String(step).split('.')[1] ?? '').length
  return Number(value.toFixed(decimals))
}

// Campo numerico com - e +: da pra ajustar no clique sem mirar no texto.
export function NumberStepper({ value, onChange, label, min = -Infinity, max = Infinity, step = 1, zeroLabel, id }: NumberStepperProps) {
  // Enquanto digita, o texto fica num rascunho; so vira numero ao sair do campo ou no Enter.
  const [draft, setDraft] = useState<string | null>(null)
  const clamp = (next: number) => Math.min(max, Math.max(min, roundToStep(next, step)))
  const shown = draft ?? (value === 0 && zeroLabel ? zeroLabel : String(value))

  function commit() {
    if (draft !== null) {
      const parsed = Number.parseFloat(draft.replace(',', '.'))
      if (Number.isFinite(parsed)) {
        onChange(clamp(parsed))
      }
      setDraft(null)
    }
  }

  const buttonClass =
    'app-no-drag flex h-full w-7 items-center justify-center text-text-muted transition-colors hover:text-text-primary disabled:opacity-30'

  return (
    <div className="flex h-8 w-[112px] shrink-0 items-center rounded-md border border-line bg-raised">
      <button aria-label={`Diminuir ${label}`} className={buttonClass} disabled={value <= min} onClick={() => onChange(clamp(value - step))} type="button">
        <Minus className="h-3.5 w-3.5" />
      </button>
      <input
        aria-label={label}
        className="app-no-drag h-full min-w-0 flex-1 bg-transparent text-center font-mono text-[13px] text-text-primary tabular-nums outline-none"
        id={id}
        inputMode="decimal"
        onBlur={commit}
        onChange={(event) => setDraft(event.target.value)}
        onFocus={() => setDraft(value === 0 && zeroLabel ? '' : String(value))}
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            commit()
          }
        }}
        value={shown}
      />
      <button aria-label={`Aumentar ${label}`} className={buttonClass} disabled={value >= max} onClick={() => onChange(clamp(value + step))} type="button">
        <Plus className="h-3.5 w-3.5" />
      </button>
    </div>
  )
}
