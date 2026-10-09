import { cn } from '@/lib/utils'

interface ToggleProps {
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
  id?: string
}

export function Toggle({ checked, onChange, disabled, id }: ToggleProps) {
  return (
    // Switch visual simples que delega o estado real para o componente pai.
    // O id deixa um <label htmlFor> dar nome acessivel e area de clique maior.
    <button
      aria-checked={checked}
      className={cn(
        'app-no-drag relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border transition-colors duration-150',
        checked ? 'border-text-primary bg-text-primary' : 'border-line-strong bg-raised',
        disabled && 'cursor-not-allowed opacity-45',
      )}
      disabled={disabled}
      id={id}
      onClick={() => onChange(!checked)}
      role="switch"
      type="button"
    >
      <span
        className={cn(
          'pointer-events-none inline-block h-3.5 w-3.5 rounded-full transition-transform duration-150',
          checked ? 'translate-x-[17px] bg-black' : 'translate-x-[2px] bg-text-muted',
        )}
      />
    </button>
  )
}
