import { Pause, Play } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import { buildCaptionCards, SAMPLE_CAPTION, type CaptionOptions } from '@/lib/captionPreview'
import { cn } from '@/lib/utils'
import type { HardsubFormat } from '@/types/subtitle'

interface CaptionMonitorProps {
  options: CaptionOptions
  format: HardsubFormat
}

// Tempo de tela de cada legenda na previa e quadros por segundo do timecode.
const CARD_MS = 1400
const FPS = 30

// Timecode de editor (HH:MM:SS:QQ) do inicio de cada legenda.
function formatTimecode(ms: number): string {
  const totalFrames = Math.floor((ms / 1000) * FPS)
  const frames = totalFrames % FPS
  const totalSeconds = Math.floor(totalFrames / FPS)
  const pad = (value: number) => String(value).padStart(2, '0')
  return `00:${pad(Math.floor(totalSeconds / 60))}:${pad(totalSeconds % 60)}:${pad(frames)}`
}

// Monitor de programa do Inspetor: mostra a frase de exemplo como ela vai sair,
// no formato escolhido, trocando de legenda como no video.
export function CaptionMonitor({ options, format }: CaptionMonitorProps) {
  const cards = useMemo(() => buildCaptionCards(SAMPLE_CAPTION, options), [options])
  const [tick, setTick] = useState(0)
  const [playing, setPlaying] = useState(true)
  // O modulo mantem o indice valido quando a quantidade de legendas muda.
  const index = tick % Math.max(1, cards.length)
  const isShorts = format === 'shorts'

  useEffect(() => {
    if (!playing || cards.length < 2) {
      return
    }
    const timer = window.setInterval(() => setTick((current) => current + 1), CARD_MS)
    return () => window.clearInterval(timer)
  }, [playing, cards.length])

  return (
    <figure className="overflow-hidden rounded-lg border border-line bg-monitor">
      <div className="flex h-[280px] items-center justify-center p-4">
        <div
          className={cn('relative border border-white/10', isShorts ? 'aspect-[9/16] h-full' : 'aspect-video w-full')}
          data-testid="caption-frame"
        >
          {/* Margem de seguranca de titulo, como o guia do Premiere. */}
          <div aria-hidden="true" className="absolute inset-[8%] border border-dashed border-white/[0.07]" />

          <p
            aria-live="off"
            className={cn(
              'absolute inset-x-[6%] text-center leading-tight font-bold text-white [font-family:Arial,sans-serif] [paint-order:stroke_fill] [-webkit-text-stroke:3px_#000]',
              isShorts ? 'bottom-[20%] text-[13px]' : 'bottom-[5%] text-[11px]',
            )}
          >
            {cards[index]?.map((line, lineIndex) => (
              <span className="block" key={lineIndex}>
                {line}
              </span>
            ))}
          </p>
        </div>
      </div>

      {/* Barra de transporte: pausa, timecode e agulha mostrando qual legenda esta na tela. */}
      <figcaption className="flex items-center gap-3 border-t border-line bg-panel px-2 py-1.5">
        <button
          aria-label={playing ? 'Pausar prévia' : 'Tocar prévia'}
          className="app-no-drag flex h-7 w-7 items-center justify-center rounded-md text-text-secondary transition-colors hover:bg-raised hover:text-text-primary"
          onClick={() => setPlaying(!playing)}
          type="button"
        >
          {playing ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
        </button>
        <span className="font-mono text-[11px] text-text-secondary tabular-nums">{formatTimecode(index * CARD_MS)}</span>
        <div className="relative h-1 flex-1 rounded-full bg-raised">
          <div
            className="absolute inset-y-0 left-0 rounded-full bg-accent transition-[width] duration-300"
            style={{ width: `${((index + 1) / cards.length) * 100}%` }}
          />
        </div>
        <span className="font-mono text-[11px] text-text-muted tabular-nums">
          {index + 1}/{cards.length}
        </span>
      </figcaption>
    </figure>
  )
}
