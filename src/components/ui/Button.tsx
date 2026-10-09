import type { ButtonHTMLAttributes, ReactNode } from 'react'

import { cn } from '@/lib/utils'

type ButtonVariant = 'primary' | 'ghost' | 'quiet' | 'danger'
type ButtonSize = 'sm' | 'md'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  leadingIcon?: ReactNode
}

// Mapa central de variantes: primary e a acao principal da tela, ghost a secundaria,
// quiet a acao de linha (sem moldura) e danger a que interrompe algo.
const variantClasses: Record<ButtonVariant, string> = {
  primary: 'bg-text-primary text-black hover:bg-white disabled:bg-text-primary/30 disabled:text-black/60',
  ghost: 'border border-line bg-raised text-text-primary hover:border-line-strong disabled:opacity-45',
  quiet: 'text-text-secondary hover:bg-raised hover:text-text-primary disabled:opacity-45',
  danger: 'border border-status-red/30 bg-status-red/10 text-status-red hover:bg-status-red/16 disabled:opacity-45',
}

const sizeClasses: Record<ButtonSize, string> = {
  sm: 'h-8 gap-1.5 rounded-md px-2.5 text-[13px]',
  md: 'h-10 gap-2 rounded-lg px-4 text-sm',
}

export function Button({
  className,
  children,
  leadingIcon,
  type = 'button',
  variant = 'primary',
  size = 'md',
  ...props
}: ButtonProps) {
  return (
    <button
      className={cn(
        'app-no-drag inline-flex shrink-0 items-center justify-center font-medium whitespace-nowrap transition-colors duration-150 disabled:cursor-not-allowed',
        sizeClasses[size],
        variantClasses[variant],
        className,
      )}
      type={type}
      {...props}
    >
      {leadingIcon}
      <span>{children}</span>
    </button>
  )
}
