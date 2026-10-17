// Estado da Pre-edicao que aprende: a lista de brutos e os itens da fila.
import { getFileName } from '@/lib/utils'
import type { PreeditJobRequest, PreeditSettings, PreeditTask, PreeditTaskEvent } from '@/types/preedit'

export const defaultPreeditSettings: PreeditSettings = {
  mode: 'learn',
  minutes: 20,
  zoomStyle: 'aproximando',
  moldePath: '',
}

const VIDEO_EXTENSIONS = ['.mp4', '.mkv', '.mov', '.m4v']

function isVideo(path: string): boolean {
  const lower = path.toLowerCase()
  return VIDEO_EXTENSIONS.some((extension) => lower.endsWith(extension))
}

// Junta os brutos novos aos que ja estao na lista: so video, sem repetir, na ordem do nome do arquivo
// (o OBS nomeia pela data e hora, entao a ordem do nome e a ordem da gravacao).
export function addSources(current: string[], incoming: string[]): string[] {
  const byKey = new Map(current.map((path) => [path.toLowerCase(), path]))
  for (const path of incoming) {
    if (isVideo(path) && !byKey.has(path.toLowerCase())) {
      byKey.set(path.toLowerCase(), path)
    }
  }
  return [...byKey.values()].sort((a, b) => getFileName(a).toLowerCase().localeCompare(getFileName(b).toLowerCase()))
}

// Insere ou atualiza o item do evento; o mais novo entra no topo.
export function upsertPreeditTask(tasks: PreeditTask[], event: PreeditTaskEvent): PreeditTask[] {
  const current = tasks.find((task) => task.id === event.taskId) ?? null
  const next: PreeditTask = {
    ...event,
    id: event.taskId,
    progress: event.progress ?? current?.progress ?? null,
    warnings: event.warnings.length ? event.warnings : (current?.warnings ?? []),
    result: event.result ?? current?.result,
    request: current?.request ?? null,
    createdAt: current?.createdAt ?? Date.now(),
  }
  return current ? tasks.map((task) => (task.id === next.id ? next : task)) : [next, ...tasks]
}

// Resposta do "Gerar"/"Ensinar": os eventos costumam chegar antes dela, entao o item que ja existe so
// ganha o pedido (pro "Tentar de novo"); o status dele nao volta pra fila.
export function attachPreeditRequest(tasks: PreeditTask[], taskId: string, title: string, request: PreeditJobRequest): PreeditTask[] {
  const base = tasks.some((task) => task.id === taskId)
    ? tasks
    : upsertPreeditTask(tasks, {
        taskId,
        kind: request.kind,
        title,
        status: 'queued',
        stage: 'queued',
        message: 'Tarefa adicionada a fila.',
        progress: null,
        warnings: [],
      })
  return base.map((task) => (task.id === taskId ? { ...task, request } : task))
}
