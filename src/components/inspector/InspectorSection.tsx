import { ChevronRight } from 'lucide-react'
import { useId, useState, type ReactNode } from 'react'

import { cn } from '@/lib/utils'

interface InspectorSectionProps {
  title: string
  // Resumo dos valores atuais, visivel com a secao fechada.
  summary?: string
  defaultOpen?: boolean
  children: ReactNode
}

// Secao recolhivel do Inspetor: o essencial fica aberto, o tecnico fica guardado.
export function InspectorSection({ title, summary, defaultOpen = false, children }: InspectorSectionProps) {
  const [open, setOpen] = useState(defaultOpen)
  const contentId = useId()

  return (
    <section className="border-t border-line">
      <button
        aria-controls={contentId}
        aria-expanded={open}
        className="app-no-drag flex w-full items-center gap-2 px-4 py-3 text-left transition-colors hover:bg-raised/50"
        onClick={() => setOpen(!open)}
        type="button"
      >
        <ChevronRight
          className={cn('h-3.5 w-3.5 shrink-0 text-text-muted transition-transform duration-150', open && 'rotate-90')}
        />
        <span className="text-[13px] font-semibold text-text-primary">{title}</span>
        {!open && summary ? <span className="ml-auto truncate pl-3 text-xs text-text-muted">{summary}</span> : null}
      </button>
      {open ? (
        <div className="space-y-3 px-4 pt-1 pb-4" id={contentId}>
          {children}
        </div>
      ) : null}
    </section>
  )
}
