import { describe, expect, test } from 'vitest'

import { addSources, attachPreeditRequest, upsertPreeditTask } from '@/store/preeditState'
import type { PreeditTaskEvent } from '@/types/preedit'

const event = (overrides: Partial<PreeditTaskEvent> = {}): PreeditTaskEvent => ({
  taskId: 't1',
  kind: 'edit',
  title: '2026-10-16 14-00-00.mkv +1',
  status: 'processing',
  stage: 'transcribing',
  message: 'Fala [1/2]',
  progress: 10,
  warnings: [],
  ...overrides,
})

describe('addSources', () => {
  test('addSources ignores duplicates and non-videos', () => {
    expect(addSources(['D:/b.mkv'], ['D:/A.mp4', 'D:/B.MKV', 'D:/notas.txt'])).toEqual(['D:/A.mp4', 'D:/b.mkv'])
  })

  test('ordena pelo nome do arquivo (data e hora do OBS), nao pela pasta', () => {
    const later = 'C:/videos/2026-10-16 15-10-00.mkv'
    const earlier = 'E:/bruto/2026-10-16 14-00-00.mkv'
    expect(addSources([], [later, earlier])).toEqual([earlier, later])
  })
})

describe('upsertPreeditTask', () => {
  test('cria o item no topo e atualiza pelo id', () => {
    const created = upsertPreeditTask([], event())
    const updated = upsertPreeditTask(created, event({ status: 'completed', stage: 'done', progress: 100, result: { xmlPath: 'X.xml' } }))

    expect(created).toHaveLength(1)
    expect(updated).toHaveLength(1)
    expect(updated[0]).toMatchObject({ id: 't1', status: 'completed', result: { xmlPath: 'X.xml' } })
    expect(updated[0]?.createdAt).toBe(created[0]?.createdAt)
  })

  test('progresso sem numero mantem o anterior', () => {
    const tasks = upsertPreeditTask(upsertPreeditTask([], event({ progress: 40 })), event({ progress: null }))
    expect(tasks[0]?.progress).toBe(40)
  })
})

describe('attachPreeditRequest', () => {
  const request = { kind: 'edit' as const, request: { recordings: ['A.mkv'], minutes: 20, moldePath: '', zoomStyle: 'aproximando' as const } }

  test('o item que ja chegou ganha o pedido sem voltar pra fila', () => {
    const tasks = attachPreeditRequest(upsertPreeditTask([], event()), 't1', 'A.mkv', request)
    expect(tasks[0]).toMatchObject({ status: 'processing', request })
  })

  test('sem evento ainda, entra na fila com o pedido', () => {
    const tasks = attachPreeditRequest([], 't2', 'A.mkv', request)
    expect(tasks[0]).toMatchObject({ id: 't2', title: 'A.mkv', status: 'queued', kind: 'edit', request })
  })
})
