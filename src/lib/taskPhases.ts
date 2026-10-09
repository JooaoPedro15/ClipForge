// Video da entrada "Versao em chines" passa por duas etapas (transcricao, depois traducao e
// queima). Aqui as duas viram um estado so, pro item da fila contar a historia inteira.
import type { HardsubJobState, SubtitleTask, SubtitleTaskStatus } from '@/types/subtitle'

export interface TaskPhase {
  // Estado efetivo: o que o icone e a contagem da fila mostram.
  status: SubtitleTaskStatus
  progress: number | null
  // Etapa em andamento (null quando ja acabou ou parou).
  step: { index: 1 | 2; label: string } | null
  message: string
  // Job da queima automatica, quando ja existe.
  burn: HardsubJobState | null
}

const TRANSCRIBING = { index: 1, label: 'Transcrição' } as const
const BURNING = { index: 2, label: 'Tradução e queima' } as const

export function autoBurnPhase(task: SubtitleTask): TaskPhase | null {
  if (!task.autoBurn) {
    return null
  }

  if (task.status !== 'completed') {
    const active = task.status === 'queued' || task.status === 'preparing' || task.status === 'processing'
    return {
      status: task.status,
      progress: task.progress,
      step: active ? TRANSCRIBING : null,
      message: task.status === 'queued' ? 'Esperando a GPU pra transcrever.' : task.message,
      burn: null,
    }
  }

  const burn = task.hardsubJobs[task.autoBurn] ?? null
  if (!burn) {
    // Entre o fim da transcricao e o primeiro evento da queima.
    return { status: 'queued', progress: null, step: BURNING, message: 'Esperando a GPU pra traduzir e queimar.', burn }
  }
  if (burn.status === 'completed') {
    return { status: 'completed', progress: 100, step: null, message: 'Vídeo em chinês pronto, ao lado do original.', burn }
  }
  if (burn.status === 'error' || burn.status === 'cancelled') {
    return { status: burn.status, progress: null, step: null, message: 'A tradução ou a queima parou com erro.', burn }
  }
  return { status: burn.status, progress: burn.progress, step: BURNING, message: burn.message, burn }
}

export function effectiveStatus(task: SubtitleTask): SubtitleTaskStatus {
  return autoBurnPhase(task)?.status ?? task.status
}
