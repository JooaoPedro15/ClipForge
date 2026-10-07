import { describe, expect, it, vi } from 'vitest'

import { SequentialJobQueue, type JobResult, type QueuedJob } from './gpuQueue'

// Job controlavel: o teste decide quando ele termina e o que devolve.
function controlledJob(id: string, log: string[]) {
  let finish: (result: JobResult) => void = () => {}
  const job: QueuedJob = {
    id,
    onQueued: (position, isNext) => log.push(`${id}:fila ${position}${isNext ? ' (proximo)' : ''}`),
    run: () => {
      log.push(`${id}:rodando`)
      return new Promise<JobResult>((resolve) => {
        finish = resolve
      })
    },
  }
  return { job, finish: (result: JobResult = 'done') => finish(result) }
}

const flush = () => new Promise<void>((resolve) => setImmediate(resolve))

describe('SequentialJobQueue', () => {
  it('roda um job por vez, na ordem, e avisa a posicao de quem espera', async () => {
    const log: string[] = []
    const queue = new SequentialJobQueue()
    const a = controlledJob('a', log)
    const b = controlledJob('b', log)

    queue.enqueue(a.job)
    queue.enqueue(b.job)
    expect(queue.busy).toBe(true)
    expect(queue.size).toBe(1)
    expect(log).toEqual(['a:fila 1 (proximo)', 'a:rodando', 'b:fila 1'])

    a.finish()
    await flush()
    expect(log.slice(3)).toEqual(['b:fila 1 (proximo)', 'b:rodando'])

    b.finish()
    await flush()
    expect(queue.busy).toBe(false)
  })

  it('remove um job que ainda espera e renumera os outros', () => {
    const log: string[] = []
    const queue = new SequentialJobQueue()
    const a = controlledJob('a', log)
    const b = controlledJob('b', log)
    const c = controlledJob('c', log)
    queue.enqueue(a.job)
    queue.enqueue(b.job)
    queue.enqueue(c.job)
    log.length = 0

    expect(queue.has('b')).toBe(true)
    expect(queue.remove('b')).toBe(true)
    expect(queue.remove('a')).toBe(false)
    expect(queue.has('b')).toBe(false)
    expect(log).toEqual(['c:fila 1'])
  })

  it("'requeue-front' devolve o job pro topo da fila (retry em CPU)", async () => {
    const log: string[] = []
    const queue = new SequentialJobQueue()
    const a = controlledJob('a', log)
    const b = controlledJob('b', log)
    queue.enqueue(a.job)
    queue.enqueue(b.job)
    log.length = 0

    a.finish('requeue-front')
    await flush()

    expect(log).toEqual(['a:fila 1 (proximo)', 'b:fila 2', 'a:rodando', 'b:fila 1'])
  })

  it('erro dentro de um job nao trava a fila', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const log: string[] = []
    const queue = new SequentialJobQueue()
    queue.enqueue({ id: 'quebra', onQueued: () => {}, run: () => Promise.reject(new Error('boom')) })
    const b = controlledJob('b', log)
    queue.enqueue(b.job)
    await flush()

    expect(log).toContain('b:rodando')
    vi.restoreAllMocks()
  })
})
