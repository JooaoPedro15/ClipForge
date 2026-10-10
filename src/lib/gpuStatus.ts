// Status da fila unica de GPU: transcricao, queima, Pre-Editor e Cortes rodam um por vez,
// entao o estado e um so pro app inteiro, nao por ferramenta.
interface GpuTaskLike {
  fileName: string
  status: string
}

export interface GpuStatus {
  // Arquivo que esta usando a GPU agora (null = livre).
  busyWith: string | null
  queued: number
}

// Um grupo por ferramenta (legendas, pre-edicao, cortes): todos dividem a mesma GPU.
export function getGpuStatus(...groups: GpuTaskLike[][]): GpuStatus {
  const all = groups.flat()
  const running = all.find((task) => task.status === 'processing' || task.status === 'preparing')
  return {
    busyWith: running?.fileName ?? null,
    queued: all.filter((task) => task.status === 'queued').length,
  }
}

// Cada queima tambem ocupa a GPU, mesmo com a legenda da tarefa ja pronta.
export function subtitleGpuEntries<T extends GpuTaskLike & { hardsubJobs: Partial<Record<string, { status: string }>> }>(
  tasks: T[],
): GpuTaskLike[] {
  return tasks.flatMap((task) => [
    task,
    ...Object.values(task.hardsubJobs).flatMap((job) => (job ? [{ fileName: task.fileName, status: job.status }] : [])),
  ])
}
