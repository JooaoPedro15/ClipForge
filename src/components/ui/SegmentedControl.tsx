import { cn } from '@/lib/utils'

interface SegmentedControlProps<T extends string> {
  value: T
  onChange: (value: T) => void
  options: Array<{ value: T; label: string }>
  label: string
  className?: string
}

// Para 2 ou 3 opcoes: todas ficam a vista e a troca e um clique, sem abrir menu.
export function SegmentedControl<T extends string>({ value, onChange, options, label, className }: SegmentedControlProps<T>) {
  return (
    <div aria-label={label} className={cn('flex rounded-md border border-line bg-app p-0.5', className)} role="radiogroup">
      {options.map((option) => {
        const isSelected = option.value === value
        return (
          <button
            aria-checked={isSelected}
            className={cn(
              'app-no-drag h-7 flex-1 rounded-[5px] px-2 text-[13px] font-medium whitespace-nowrap transition-colors',
              isSelected ? 'bg-raised text-text-primary shadow-[0_1px_0_rgba(255,255,255,0.06)_inset]' : 'text-text-muted hover:text-text-secondary',
            )}
            key={option.value}
            onClick={() => onChange(option.value)}
            role="radio"
            type="button"
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}
