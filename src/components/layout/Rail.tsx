import { Captions, Clapperboard, Scissors } from 'lucide-react'

import { cn } from '@/lib/utils'
import type { ToolId } from '@/types/subtitle'

interface RailProps {
  activeTool: ToolId
  onSelect: (tool: ToolId) => void
}

export const tools = [
  {
    id: 'subtitle-forge' as const,
    label: 'Legendas',
    hint: 'Transcreve, traduz e queima legenda no vídeo',
    icon: Captions,
  },
  {
    id: 'clip-splitter' as const,
    label: 'Pré-edição',
    hint: 'Encurta as pausas do vídeo bruto',
    icon: Scissors,
  },
  {
    id: 'cortes' as const,
    label: 'Cortes',
    hint: 'Corta o react em clipes pro TikTok e gera o XML do Premiere',
    icon: Clapperboard,
  },
] satisfies Array<{
  id: ToolId
  label: string
  hint: string
  icon: typeof Captions
}>

// Trilho estreito (80px) de ferramentas, como a barra de paineis de um editor de video.
export function Rail({ activeTool, onSelect }: RailProps) {
  return (
    <nav aria-label="Ferramentas" className="flex w-20 shrink-0 flex-col items-stretch gap-1 border-r border-line bg-app py-3">
      {tools.map((tool) => {
        const Icon = tool.icon
        const isActive = tool.id === activeTool

        return (
          <button
            aria-current={isActive ? 'page' : undefined}
            className={cn(
              'app-no-drag relative mx-1.5 flex flex-col items-center gap-1 rounded-lg py-2.5 text-[11px] font-medium whitespace-nowrap transition-colors',
              isActive ? 'bg-raised text-text-primary' : 'text-text-muted hover:bg-panel hover:text-text-secondary',
            )}
            key={tool.id}
            onClick={() => onSelect(tool.id)}
            title={tool.hint}
            type="button"
          >
            {isActive ? (
              <span aria-hidden="true" className="absolute inset-y-2 -left-1.5 w-[3px] rounded-r-full bg-accent" />
            ) : null}
            <Icon className="h-5 w-5" strokeWidth={1.75} />
            {tool.label}
          </button>
        )
      })}
    </nav>
  )
}
