// Fila sequencial unica pros jobs que usam GPU (transcricao, queima, Pre-Editor).
// Um job por vez evita disputa de VRAM entre Whisper, NLLB/LLM e o Pre-Editor.

// 'requeue-front': o job quer rodar de novo antes dos outros (ex.: retry em CPU).
export type JobResult = 'done' | 'requeue-front'

export interface QueuedJob {
  id: string
  // position 1 = proximo da fila; isNext = vai comecar assim que a fila andar (nada rodando agora).
  onQueued: (position: number, isNext: boolean) => void
  run: () => Promise<JobResult>
}

export class SequentialJobQueue {
  private pending: QueuedJob[] = []
  private active: QueuedJob | null = null

  // Tem job rodando agora.
  get busy(): boolean {
    return this.active !== null
  }

  // Quantos jobs esperam (sem contar o que esta rodando).
  get size(): number {
    return this.pending.length
  }

  has(id: string): boolean {
    return this.pending.some((job) => job.id === id)
  }

  enqueue(job: QueuedJob, options: { front?: boolean } = {}): void {
    if (options.front) {
      this.pending.unshift(job)
    } else {
      this.pending.push(job)
    }
    this.notifyPositions()
    void this.pump()
  }

  // Tira da fila um job que ainda nao comecou. Job rodando se cancela pelo proprio modulo (kill).
  remove(id: string): boolean {
    const index = this.pending.findIndex((job) => job.id === id)
    if (index < 0) {
      return false
    }
    this.pending.splice(index, 1)
    this.notifyPositions()
    return true
  }

  private notifyPositions() {
    this.pending.forEach((job, index) => job.onQueued(index + 1, index === 0 && this.active === null))
  }

  private async pump(): Promise<void> {
    const job = this.active ? undefined : this.pending.shift()
    if (!job) {
      return
    }

    this.active = job
    // run() comeca (e avisa "iniciando") antes de renumerar quem ficou esperando.
    const running = job.run().catch((error: unknown) => {
      console.error('[gpu-queue] job falhou', error)
      return 'done' as const
    })
    this.notifyPositions()

    const result = await running
    this.active = null
    if (result === 'requeue-front') {
      this.pending.unshift(job)
    }
    this.notifyPositions()
    await this.pump()
  }
}

// Instancia unica do app: todos os IPCs que usam GPU entram nesta fila.
export const gpuQueue = new SequentialJobQueue()
