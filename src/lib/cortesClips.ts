// Logica pura da tela de Cortes: etapa da fila, N melhores e tempos.
import type { CortesClip, CortesDurations } from '@/types/cortes'

interface CortesStep {
  index: 1 | 2 | 3 | 4
  label: string
}

// Estagios que o cortes_service.py emite -> etapa mostrada no item (o juiz, se ligado na CLI, conta como Cortes).
const STEPS: Record<string, CortesStep> = {
  extracting: { index: 1, label: 'Leitura' },
  transcribing: { index: 2, label: 'Transcrição' },
  choosing: { index: 3, label: 'Cortes' },
  judging: { index: 3, label: 'Cortes' },
  titling: { index: 4, label: 'Títulos' },
}

export function cortesStep(stage: string): CortesStep | null {
  return STEPS[stage] ?? null
}

// Os N clipes de maior nota (sem nota conta como a menor), devolvidos na ordem do filme.
export function topClips(clips: CortesClip[], count: number): number[] {
  const ranked = [...clips].sort((a, b) => (b.score ?? -1) - (a.score ?? -1) || a.n - b.n)
  return ranked
    .slice(0, Math.max(0, count))
    .map((clip) => clip.n)
    .sort((a, b) => a - b)
}

// 144.4 -> "2:24"; 3723 -> "1:02:03".
export function formatClock(seconds: number): string {
  const whole = Math.floor(seconds)
  const pad = (value: number) => String(value).padStart(2, '0')
  const hours = Math.floor(whole / 3600)
  const minutes = Math.floor((whole % 3600) / 60)
  return hours ? `${hours}:${pad(minutes)}:${pad(whole % 60)}` : `${minutes}:${pad(whole % 60)}`
}

// Mesmo formato do Python (cortes/timebase.parse_clock): s, m:s ou h:m:s, decimal so no fim. Vazio = sem limite.
export function isClockText(text: string): boolean {
  const trimmed = text.trim()
  return trimmed === '' || /^\d+(:\d+){0,2}([.,]\d+)?$/.test(trimmed)
}

export function sameDurations(a: CortesDurations, b: CortesDurations): boolean {
  return a.minSec === b.minSec && a.targetSec === b.targetSec && a.maxSec === b.maxSec
}
