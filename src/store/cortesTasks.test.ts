import { describe, expect, test } from 'vitest'

import { addLoadedCortesTask, loadedCortesTask, patchCortesXml, startCortesTask, upsertCortesTask } from '@/store/cortesTasks'
import type { CortesAnalysisSummary, CortesAnalyzeOptions, CortesDoneEvent, CortesProgressEvent } from '@/types/cortes'

const analysis: CortesAnalysisSummary = {
  analysisPath: 'E:\\Bruto\\react.cortes.json',
  sourcePath: 'E:\\Bruto\\react.mp4',
  durationSec: 7298,
  start: 0,
  end: 7298,
  durations: { minSec: 70, targetSec: 150, maxSec: 240 },
  clips: [{ n: 1, start: 0, end: 150, title: 'A', hook: 7, score: 6.1 }],
  warnings: ['aviso'],
}

const progress = (overrides: Partial<CortesProgressEvent> = {}): CortesProgressEvent => ({
  taskId: 't1',
  kind: 'analyze',
  sourcePath: 'E:\\Bruto\\react.mp4',
  sourceName: 'react.mp4',
  status: 'processing',
  stage: 'transcribing',
  message: 'Transcrevendo o filme...',
  progress: 40,
  ...overrides,
})

const done = (overrides: Partial<CortesDoneEvent> = {}): CortesDoneEvent => ({
  ...progress(),
  status: 'completed',
  stage: 'done',
  progress: 100,
  completedAt: 2,
  durationSec: 90,
  analysis,
  ...overrides,
})

const options: CortesAnalyzeOptions = { start: '', end: '', filmTrack: 1, micTrack: 2, minSec: 70, targetSec: 150, maxSec: 240, titlesWithAi: true }

describe('upsertCortesTask', () => {
  test('progresso cria o item no topo e o fim traz a lista de clipes', () => {
    const older = upsertCortesTask([], progress({ taskId: 't0' }))
    const tasks = upsertCortesTask(older, progress())
    expect(tasks.map((task) => task.id)).toEqual(['t1', 't0'])

    const finished = upsertCortesTask(tasks, done())
    expect(finished[0]).toMatchObject({ status: 'completed', analysis, durationSec: 90, error: null })
  })

  test('evento sem progresso mantem o ultimo, e sem avisos mantem os anteriores', () => {
    const first = upsertCortesTask([], progress({ warnings: ['sem cuda'] }))
    const next = upsertCortesTask(first, progress({ progress: null, warnings: undefined, stage: 'titling' }))
    expect(next[0]).toMatchObject({ progress: 40, warnings: ['sem cuda'], stage: 'titling' })
  })

  test('analise nova do mesmo bruto tira da fila o item antigo (os numeros dos clipes mudaram)', () => {
    const loaded = addLoadedCortesTask([], loadedCortesTask('antigo', 'E:\\Bruto\\react.mp4', analysis))
    const running = upsertCortesTask(loaded, progress({ taskId: 'novo' }))
    expect(running.map((task) => task.id)).toEqual(['novo', 'antigo'])
    expect(upsertCortesTask(running, done({ taskId: 'novo' })).map((task) => task.id)).toEqual(['novo'])
  })

  test('lista nova zera o XML gerado antes (a numeracao mudou)', () => {
    const tasks = patchCortesXml(upsertCortesTask([], done()), 't1', { status: 'done', outputPath: 'E:\\Bruto\\react.cortes.xml', error: null })
    expect(tasks[0]?.xml?.status).toBe('done')
    expect(upsertCortesTask(tasks, done({ kind: 'resegment' }))[0]?.xml).toBeNull()
  })
})

describe('startCortesTask', () => {
  test('item que ja chegou pelo processo principal so recebe as opcoes', () => {
    const tasks = upsertCortesTask([], progress({ status: 'preparing', stage: 'starting' }))
    const started = startCortesTask(tasks, progress({ status: 'queued', stage: 'queued' }), options)
    expect(started[0]).toMatchObject({ status: 'preparing', request: options })
  })

  test('item que ainda nao chegou e criado na fila', () => {
    const started = startCortesTask([], progress({ status: 'queued', stage: 'queued', progress: null }), options)
    expect(started[0]).toMatchObject({ status: 'queued', request: options })
  })
})

describe('analise carregada', () => {
  test('entra pronta, com os avisos, e nao duplica', () => {
    const task = loadedCortesTask('l1', 'E:\\Bruto\\react.mp4', analysis)
    expect(task).toMatchObject({ status: 'completed', stage: 'loaded', sourceName: 'react.mp4', warnings: ['aviso'], analysis })

    const once = addLoadedCortesTask([], task)
    expect(addLoadedCortesTask(once, loadedCortesTask('l2', 'E:\\Bruto\\react.mp4', analysis))).toHaveLength(1)
  })
})

describe('patchCortesXml', () => {
  test('mexe so no item certo', () => {
    const other = { ...analysis, analysisPath: 'E:\\Bruto\\outro.cortes.json' }
    const tasks = upsertCortesTask(upsertCortesTask([], done({ taskId: 'a' })), done({ taskId: 'b', analysis: other }))
    const patched = patchCortesXml(tasks, 'a', { status: 'running', outputPath: null, error: null })
    expect(patched.find((task) => task.id === 'a')?.xml?.status).toBe('running')
    expect(patched.find((task) => task.id === 'b')?.xml).toBeNull()
  })
})
