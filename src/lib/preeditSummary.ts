// Textos curtos da Pre-edicao que aprende: o resumo de cada item pronto e o aviso do sistema.
import type { Notice } from '@/lib/finishNotices'
import type { PreeditTaskEvent } from '@/types/preedit'

function count(value: unknown): number {
  return Array.isArray(value) ? value.length : 0
}

function plural(amount: number, one: string, many: string): string {
  return `${amount} ${amount === 1 ? one : many}`
}

// "sem zoom (Longo 1)" e "bruto disponivel (a.mp4): ensine..." viram so o motivo.
function reasonKey(reason: string): string {
  return (reason.split(' (')[0] ?? reason).split(':')[0]?.trim() ?? reason
}

// Ensino pronto: "4 ensinados, 2 pulados (ja ensinada), 1 falha".
export function teachSummary(result: Record<string, unknown>): string {
  const parts = [plural(count(result.taught), 'ensinado', 'ensinados')]
  const skipped = Array.isArray(result.skipped) ? result.skipped : []
  if (skipped.length) {
    const reasons = new Map<string, number>()
    for (const item of skipped) {
      const reason = typeof item === 'object' && item && 'reason' in item ? reasonKey(String(item.reason)) : 'outro motivo'
      reasons.set(reason, (reasons.get(reason) ?? 0) + 1)
    }
    const sorted = [...reasons.entries()].sort((a, b) => b[1] - a[1])
    const detail = sorted.length === 1 ? sorted[0]?.[0] : sorted.map(([reason, amount]) => `${amount} ${reason}`).join(', ')
    parts.push(`${plural(skipped.length, 'pulado', 'pulados')} (${detail})`)
  }
  const failed = count(result.failed)
  if (failed) {
    parts.push(plural(failed, 'falha', 'falhas'))
  }
  return parts.join(', ')
}

function clock(totalSeconds: number): string {
  const rounded = Math.round(totalSeconds)
  const minutes = Math.floor(rounded / 60)
  const seconds = rounded % 60
  if (!minutes) {
    return `${seconds} s`
  }
  return seconds ? `${minutes} min ${seconds} s` : `${minutes} min`
}

// Edicao pronta: "12 min 30 s, 48 trechos, 9 zooms".
export function editSummary(result: Record<string, unknown>): string {
  const duration = typeof result.durationSec === 'number' ? result.durationSec : 0
  const segments = typeof result.segments === 'number' ? result.segments : 0
  const zooms = typeof result.zooms === 'number' ? result.zooms : 0
  return [clock(duration), plural(segments, 'trecho', 'trechos'), zooms ? plural(zooms, 'zoom', 'zooms') : 'sem zoom'].join(', ')
}

function firstLine(text: string | undefined): string {
  const line = ((text ?? '').split('\n')[0] ?? '').trim()
  return line.length > 140 ? `${line.slice(0, 137)}...` : line
}

export function preeditNotice(event: PreeditTaskEvent): Notice | null {
  if (event.status === 'completed') {
    const result = event.result ?? {}
    return event.kind === 'edit'
      ? { title: 'Pré-edição pronta', body: `${event.title}: ${editSummary(result)}` }
      : { title: 'Ensino concluído', body: teachSummary(result) }
  }
  if (event.status === 'error') {
    return { title: event.kind === 'edit' ? 'A pré-edição parou com erro' : 'O ensino parou com erro', body: `${event.title}: ${firstLine(event.error)}` }
  }
  return null
}
