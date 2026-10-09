import { useId, type ReactNode } from 'react'

import { Toggle } from '@/components/ui/Toggle'

// Campo de texto no padrao do Inspetor.
export const inspectorInputClass =
  'app-no-drag h-9 w-full rounded-md border border-line bg-raised px-3 text-sm text-text-primary outline-none transition-colors placeholder:text-text-muted hover:border-line-strong focus:border-text-muted'

interface FieldRowProps {
  label: string
  hint?: string
  htmlFor?: string
  children: ReactNode
}

// Nome (e dica) a esquerda, controle a direita: o desenho de painel de propriedades.
export function FieldRow({ label, hint, htmlFor, children }: FieldRowProps) {
  return (
    <div className="flex items-center justify-between gap-3">
      <label className="min-w-0 cursor-pointer" htmlFor={htmlFor}>
        <span className="block text-[13px] text-text-primary">{label}</span>
        {hint ? <span className="block text-xs leading-snug text-text-muted">{hint}</span> : null}
      </label>
      {children}
    </div>
  )
}

// Nome em cima e controle ocupando a largura toda (selects e campos de texto).
export function StackedField({ label, hint, htmlFor, children }: FieldRowProps) {
  return (
    <div className="space-y-1.5">
      <label className="block text-[13px] text-text-primary" htmlFor={htmlFor}>
        {label}
      </label>
      {children}
      {hint ? <p className="text-xs leading-snug text-text-muted">{hint}</p> : null}
    </div>
  )
}

interface ToggleFieldProps {
  label: string
  hint?: string
  checked: boolean
  onChange: (checked: boolean) => void
}

// Liga/desliga com o texto clicavel (o label aponta pro switch pelo id).
export function ToggleField({ label, hint, checked, onChange }: ToggleFieldProps) {
  const id = useId()
  return (
    <FieldRow hint={hint} htmlFor={id} label={label}>
      <Toggle checked={checked} id={id} onChange={onChange} />
    </FieldRow>
  )
}
