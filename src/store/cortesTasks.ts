// Fila de Cortes na tela: cada evento do processo principal vira o estado de um item.
import { getFileName } from '@/lib/utils'
import type {
  CortesAnalysisSummary,
  CortesAnalyzeOptions,
  CortesDoneEvent,
  CortesErrorEvent,
  CortesProgressEvent,
  CortesTask,
  CortesXmlState,
} from '@/types/cortes'

export type CortesEvent = CortesProgressEvent | CortesDoneEvent | CortesErrorEvent

export function isCortesActive(status: string): boolean {
  return status === 'queued' || status === 'preparing' || status === 'processing'
}

// Insere ou atualiza o item do evento; o mais novo entra no topo.
export function upsertCortesTask(tasks: CortesTask[], event: CortesEvent): CortesTask[] {
  const current = tasks.find((task) => task.id === event.taskId) ?? null
  const next: CortesTask = {
    id: event.taskId,
    kind: event.kind,
    sourcePath: event.sourcePath,
    sourceName: event.sourceName,
    status: event.status,
    stage: event.stage,
    message: event.message,
    progress: event.progress ?? current?.progress ?? null,
    queuePosition: event.queuePosition ?? null,
    warnings: event.warnings ?? current?.warnings ?? [],
    analysis: event.analysis ?? current?.analysis ?? null,
    request: current?.request ?? null,
    createdAt: current?.createdAt ?? Date.now(),
    startedAt: event.startedAt ?? current?.startedAt ?? null,
    completedAt: event.completedAt ?? null,
    durationSec: event.durationSec ?? null,
    error: 'error' in event ? event.error : null,
    // Lista nova (analise ou refazer) muda a numeracao: o XML de antes deixa de valer.
    xml: event.analysis ? null : (current?.xml ?? null),
  }

  const updated = current ? tasks.map((task) => (task.id === next.id ? next : task)) : [next, ...tasks]
  // O <bruto>.cortes.json foi regravado: outro item parado do mesmo bruto mostraria clipes que nao
  // existem mais, e o "Gerar XML" dele mandaria numeros da lista nova.
  const path = event.analysis?.analysisPath
  return path
    ? updated.filter((task) => task.id === next.id || isCortesActive(task.status) || task.analysis?.analysisPath !== path)
    : updated
}

// Resposta do "Analisar": os eventos do processo principal costumam chegar antes dela, entao
// o item que ja existe so ganha as opcoes (pro "Tentar de novo"); o status dele nao volta pra fila.
export function startCortesTask(tasks: CortesTask[], event: CortesProgressEvent, request: CortesAnalyzeOptions): CortesTask[] {
  const base = tasks.some((task) => task.id === event.taskId) ? tasks : upsertCortesTask(tasks, event)
  return base.map((task) => (task.id === event.taskId ? { ...task, request } : task))
}

// Bruto que ja tinha <bruto>.cortes.json: entra pronto, sem reprocessar.
export function loadedCortesTask(id: string, sourcePath: string, analysis: CortesAnalysisSummary): CortesTask {
  return {
    id,
    kind: 'analyze',
    sourcePath,
    sourceName: getFileName(sourcePath),
    status: 'completed',
    stage: 'loaded',
    message: 'Análise anterior carregada.',
    progress: 100,
    queuePosition: null,
    warnings: analysis.warnings,
    analysis,
    request: null,
    createdAt: Date.now(),
    startedAt: null,
    completedAt: null,
    durationSec: null,
    error: null,
    xml: null,
  }
}

// Soltar o mesmo bruto de novo nao repete o item.
export function addLoadedCortesTask(tasks: CortesTask[], task: CortesTask): CortesTask[] {
  const path = task.analysis?.analysisPath
  return tasks.some((existing) => existing.analysis?.analysisPath === path) ? tasks : [task, ...tasks]
}

export function patchCortesXml(tasks: CortesTask[], taskId: string, xml: CortesXmlState): CortesTask[] {
  return tasks.map((task) => (task.id === taskId ? { ...task, xml } : task))
}
