import { Minus, Square, X } from 'lucide-react'

import type { GpuStatus } from '@/lib/gpuStatus'
import { cn, hasClipForgeDesktopBridge } from '@/lib/utils'

interface TitlebarProps {
  gpu: GpuStatus
}

// Marca do app: uma tela com a faixa de legenda, o mesmo desenho do monitor de previa.
export function ClipForgeMark({ className }: { className?: string }) {
  return (
    <svg aria-hidden="true" className={className} fill="none" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
      <rect height="14" rx="2.5" stroke="currentColor" strokeWidth="1.6" width="19" x="2.5" y="5" />
      <rect className="fill-accent" height="2.4" rx="1.2" width="10" x="7" y="13.6" />
    </svg>
  )
}

const windowButton =
  'flex h-full w-11 items-center justify-center text-text-secondary transition-colors hover:bg-raised hover:text-text-primary'

export function Titlebar({ gpu }: TitlebarProps) {
  // Sem o preload (Vite puro no navegador) os controles da janela nao fazem nada.
  const hasDesktopBridge = hasClipForgeDesktopBridge()
  const busy = gpu.busyWith !== null

  return (
    <header className="app-drag flex h-10 shrink-0 items-center border-b border-line bg-app pl-4 select-none">
      <div className="flex items-center gap-2 text-text-primary">
        <ClipForgeMark className="h-5 w-5" />
        <span className="text-[13px] font-semibold">ClipForge</span>
      </div>

      {/* Estado da fila unica de GPU, valido pra todas as ferramentas. */}
      <div className="ml-auto flex min-w-0 items-center gap-3 pr-3 text-xs text-text-secondary" role="status">
        <span className="flex min-w-0 items-center gap-2">
          <span
            aria-hidden="true"
            className={cn('h-2 w-2 shrink-0 rounded-full', busy ? 'animate-pulse bg-accent' : 'bg-status-green')}
          />
          <span className="truncate">{busy ? `GPU ocupada com ${gpu.busyWith}` : 'GPU livre'}</span>
        </span>
        {gpu.queued > 0 ? <span className="shrink-0 text-text-muted">{gpu.queued} na fila</span> : null}
      </div>

      {hasDesktopBridge ? (
        <div className="app-no-drag flex h-full items-stretch border-l border-line">
          <button aria-label="Minimizar" className={windowButton} onClick={() => void window.clipforge.window.minimize()} type="button">
            <Minus className="h-4 w-4" />
          </button>
          <button aria-label="Maximizar" className={windowButton} onClick={() => void window.clipforge.window.maximize()} type="button">
            <Square className="h-3.5 w-3.5" />
          </button>
          <button
            aria-label="Fechar"
            className={cn(windowButton, 'hover:bg-status-red/80 hover:text-white')}
            onClick={() => void window.clipforge.window.close()}
            type="button"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      ) : (
        <span className="border-l border-line px-4 text-xs text-text-muted" title="Abra com npm run electron:dev pra usar arquivos e GPU">
          Prévia no navegador
        </span>
      )}
    </header>
  )
}
