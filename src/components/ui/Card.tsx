import type { HTMLAttributes, ReactNode } from 'react'

import { cn } from '@/lib/utils'

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode
}

export function Card({ className, children, ...props }: CardProps) {
  return (
    // Painel padrao: chapado, sem sombra, como os paineis de um editor de video.
    <div className={cn('rounded-[10px] border border-line bg-panel p-5', className)} {...props}>
      {children}
    </div>
  )
}
