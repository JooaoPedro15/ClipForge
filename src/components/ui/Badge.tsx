import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

type BadgeTone = 'green' | 'yellow' | 'blue' | 'red' | 'neutral'

interface BadgeProps {
  children: ReactNode
  tone?: BadgeTone
  className?: string
}

// A bolinha carrega a cor do estado; o texto fica legivel em qualquer tom.
// 'yellow' e o amarelo de legenda: algo rodando agora.
const dotClasses: Record<BadgeTone, string> = {
  green: 'bg-status-green',
  yellow: 'bg-accent',
  blue: 'bg-status-blue',
  red: 'bg-status-red',
  neutral: 'bg-text-muted',
}

export function Badge({ children, tone = 'neutral', className }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center gap-1.5 rounded-full border border-line bg-raised px-2 py-0.5 text-xs font-medium text-text-secondary',
        className,
      )}
    >
      <span aria-hidden="true" className={cn('h-1.5 w-1.5 rounded-full', dotClasses[tone])} />
      {children}
    </span>
  )
}
