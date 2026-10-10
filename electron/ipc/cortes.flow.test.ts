// Fluxo IPC dos Cortes: o que a tela recebe na analise, no cancelamento, no refazer e no XML.
import { existsSync, mkdirSync, rmSync, writeFileSync } from 'node:fs'
import path from 'node:path'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { CortesAnalysisSummary, CortesDoneEvent, CortesXmlResult } from '../../src/types/cortes'
import type { FakeChild } from '../testing/fakeChildProcess'
import { createSender, flush, jsonLine, makePythonRoot, project } from '../testing/ipcHarness'

const mocks = vi.hoisted(() => ({
  handlers: new Map<string, (...args: unknown[]) => unknown>(),
  children: [] as FakeChild[],
}))

vi.mock('electron', () => ({
  app: { getPath: () => 'C:\\userData' },
  ipcMain: {
    handle: (channel: string, handler: (...args: unknown[]) => unknown) => mocks.handlers.set(channel, handler),
  },
}))

vi.mock('node:child_process', async () => {
  const { createFakeChild } = await import('../testing/fakeChildProcess')
  return {
    spawn: (command: string, args: string[], options: FakeChild['options']) => {
      const child = createFakeChild(command, args, options)
      mocks.children.push(child)
      return child
    },
  }
})

const KEYS = ['sourceName', 'kind', 'status', 'stage', 'message', 'progress', 'queuePosition', 'warnings', 'error']

function analysisJson(clips: Array<[number, number, number, string, number | null]>, warnings: string[] = []) {
  return JSON.stringify({
    version: 1,
    source: { path: 'E:\\Bruto\\react.mp4', duration_sec: 7298.1, fps: 60, width: 3840, height: 1080, audio_streams: 4 },
    options: { start: 0, end: 7298.1, film_track: 0, mic_track: 1, judge_model: null, title_model: null, min_sec: 70, target_sec: 150, max_sec: 240 },
    transcript: { film: [], mic: [] },
    mic_speech: [],
    shot_cuts: [],
    candidates: [],
    clips: clips.map(([n, start, end, title, score]) => ({ n, start, end, title, hook: score === null ? null : 7, score })),
    warnings,
    timings: {},
  })
}

const status = (stage: string, message: string, extra: Record<string, unknown> = {}) =>
  jsonLine({ event: 'status', status: 'processing', stage, message, ...extra })

const scriptArgs = (python: FakeChild) => python.args.slice(1)

describe('fluxo IPC dos Cortes', () => {
  let root: string
  let sourcePath: string
  let analysisPath: string

  beforeEach(() => {
    root = makePythonRoot('cortes-flow-')
    sourcePath = path.join(root, 'react.mp4')
    analysisPath = path.join(root, 'react.cortes.json')
    vi.stubEnv('CLIPFORGE_SUBTITLE_FORGE_PATH', root)
    mocks.handlers.clear()
    mocks.children.length = 0
    vi.resetModules()
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.restoreAllMocks()
    rmSync(root, { recursive: true, force: true })
  })

  async function setup() {
    const { registerCortesHandlers } = await import('./cortes.js')
    registerCortesHandlers()
    const { sent, sender } = createSender()
    const call = <T>(channel: string, ...args: unknown[]) => mocks.handlers.get(channel)?.({ sender }, ...args) as Promise<T>
    return { sent, call }
  }

  function child(index: number): FakeChild {
    const found = mocks.children[index]
    if (!found) {
      throw new Error(`processo ${index} nao foi iniciado`)
    }
    return found
  }

  function makeTempDir(name: string) {
    const dir = path.join(root, name)
    mkdirSync(dir)
    writeFileSync(path.join(dir, 'filme.wav'), '')
    return dir
  }

  it('analise: etapas, aviso e lista de clipes no fim', async () => {
    const { sent, call } = await setup()
    const warning = 'Sem -hwaccel cuda: li o bruto na CPU.'

    await call('cortes:analyze', sourcePath, { start: '2:24,44', titlesWithAi: true })
    const python = child(0)
    expect(path.basename(python.args[0] ?? '')).toBe('cortes_service.py')
    expect(scriptArgs(python)).toEqual([
      'analyze',
      sourcePath,
      '--film-track',
      '1',
      '--mic-track',
      '2',
      '--min',
      '70',
      '--target',
      '150',
      '--max',
      '240',
      '--titles',
      'qwen2.5:7b-instruct',
      '--start',
      '2:24.44',
    ])

    python.emitStdout(status('extracting', 'Lendo o bruto... 40%', { progress: 11 }))
    python.emitStdout(jsonLine({ event: 'warning', status: 'processing', stage: 'warning', message: warning }))
    python.emitStdout(status('titling', 'Titulos: clipe 1 de 2...', { progress: 89 }))
    writeFileSync(analysisPath, analysisJson([[1, 144.44, 219.72, 'Ele volta', 7.1], [2, 219.72, 328.56, 'Clipe 02', null]], [warning]))
    python.emitStdout(jsonLine({ event: 'done', status: 'completed', stage: 'done', message: 'Analise pronta: 2 clipes.', outputPath: analysisPath, clips: 2 }))
    python.close(0)
    await flush()

    expect(project(sent, ['stage']).map((event) => event.stage)).toEqual([
      'queued',
      'queued',
      'starting',
      'extracting',
      'extracting',
      'titling',
      'done',
    ])
    const [channel, payload] = sent.at(-1) ?? []
    const done = payload as unknown as CortesDoneEvent
    expect(channel).toBe('cortes:done')
    expect(done.warnings).toEqual([warning])
    expect(done.analysis.analysisPath).toBe(analysisPath)
    expect(done.analysis.durations).toEqual({ minSec: 70, targetSec: 150, maxSec: 240 })
    expect(done.analysis.clips).toEqual([
      { n: 1, start: 144.44, end: 219.72, title: 'Ele volta', hook: 7, score: 7.1 },
      { n: 2, start: 219.72, end: 328.56, title: 'Clipe 02', hook: null, score: null },
    ])
  })

  it('cancelar o job ativo derruba o processo e apaga a pasta temporaria', async () => {
    const { sent, call } = await setup()

    const taskId = await call<string>('cortes:analyze', sourcePath, {})
    const tempDir = makeTempDir('cortes-abc')
    child(0).emitStdout(status('extracting', 'Preparando a leitura do bruto...', { progress: 1, tempDir }))
    expect(await call('cortes:cancel', taskId)).toBe(true)
    expect(child(0).killed).toBe(true)
    child(0).close(null)
    await flush()

    expect(existsSync(tempDir)).toBe(false)
    expect(project(sent, KEYS).at(-1)).toEqual({
      ch: 'cortes:error',
      sourceName: 'react.mp4',
      kind: 'analyze',
      status: 'cancelled',
      stage: 'cancelled',
      message: 'Processo cancelado pelo usuario.',
      error: 'Processo cancelado pelo usuario.',
    })
  })

  it('pasta que nao e dos cortes nunca e apagada', async () => {
    const { call } = await setup()

    const taskId = await call<string>('cortes:analyze', sourcePath, {})
    const otherDir = makeTempDir('videos')
    child(0).emitStdout(status('extracting', 'Preparando a leitura do bruto...', { progress: 1, tempDir: otherDir }))
    await call('cortes:cancel', taskId)
    child(0).close(null)
    await flush()

    expect(existsSync(otherDir)).toBe(true)
  })

  it('cancelar na fila nao sobe processo', async () => {
    const { sent, call } = await setup()

    await call('cortes:analyze', sourcePath, {})
    const queuedId = await call<string>('cortes:analyze', path.join(root, 'outro.mp4'), {})
    expect(await call('cortes:cancel', queuedId)).toBe(true)

    expect(mocks.children).toHaveLength(1)
    expect(project(sent, KEYS).at(-1)).toMatchObject({ ch: 'cortes:error', sourceName: 'outro.mp4', status: 'cancelled' })
  })

  it('erro do Python chega na tela, apaga a pasta temporaria e nao tenta em CPU', async () => {
    const { sent, call } = await setup()
    const reason = 'O bruto tem 2 faixa(s) de audio, mas a configuracao usa a faixa 3.'

    await call('cortes:analyze', sourcePath, {})
    const tempDir = makeTempDir('cortes-xyz')
    child(0).emitStdout(status('extracting', 'Preparando a leitura do bruto...', { progress: 1, tempDir }))
    child(0).emitStdout(jsonLine({ event: 'error', status: 'error', stage: 'runtime', message: 'Falha no modulo de cortes.', error: reason }))
    child(0).close(1)
    await flush()

    expect(mocks.children).toHaveLength(1)
    expect(existsSync(tempDir)).toBe(false)
    expect(project(sent, KEYS).at(-1)).toMatchObject({ ch: 'cortes:error', status: 'error', error: reason })
  })

  it('crash de GPU tenta de novo em CPU', async () => {
    const { call } = await setup()

    await call('cortes:analyze', sourcePath, {})
    child(0).close(3221226505)
    await flush()

    expect(scriptArgs(child(1))).toContain('--cpu')
  })

  it('refazer clipes reaproveita o item e devolve a lista nova', async () => {
    const { sent, call } = await setup()
    writeFileSync(analysisPath, analysisJson([[1, 0, 150, 'A', 5]]))
    const request = { sourcePath, analysisPath, minSec: 60, targetSec: 120, maxSec: 200, titlesWithAi: false }

    expect(await call('cortes:resegment', 'item-1', request)).toBe(true)
    expect(scriptArgs(child(0))).toEqual(['resegment', analysisPath, '--min', '60', '--target', '120', '--max', '200', '--titles', 'none'])
    expect(await call('cortes:resegment', 'item-1', request)).toBe(false)

    writeFileSync(analysisPath, analysisJson([[1, 0, 120, 'A', 5], [2, 120, 240, 'Clipe 02', null]]))
    child(0).emitStdout(jsonLine({ event: 'done', status: 'completed', stage: 'done', message: '2 clipes.', outputPath: analysisPath, clips: 2 }))
    child(0).close(0)
    await flush()

    const done = sent.at(-1)?.[1] as unknown as CortesDoneEvent
    expect([done.taskId, done.kind, done.analysis.clips.length]).toEqual(['item-1', 'resegment', 2])
    expect(mocks.children).toHaveLength(1)
  })

  it('carregar: com analise devolve o resumo, sem analise ou ilegivel devolve null', async () => {
    const { call } = await setup()
    vi.spyOn(console, 'error').mockImplementation(() => undefined)

    expect(await call('cortes:load', sourcePath)).toBeNull()
    writeFileSync(analysisPath, analysisJson([[1, 0, 150, 'A', 5]], ['aviso']))
    const summary = await call<CortesAnalysisSummary>('cortes:load', sourcePath)
    expect(summary).toMatchObject({ analysisPath, warnings: ['aviso'], start: 0, end: 7298.1 })
    expect(summary.clips[0]?.title).toBe('A')
    writeFileSync(analysisPath, '{"version": 9}')
    expect(await call('cortes:load', sourcePath)).toBeNull()
    expect(mocks.children).toHaveLength(0)
  })

  it('gerar XML roda fora da fila e devolve o caminho', async () => {
    const { call } = await setup()
    const xmlPath = path.join(root, 'react.cortes.xml')

    await call('cortes:analyze', sourcePath, {})
    const pending = call<CortesXmlResult>('cortes:generate-xml', { analysisPath, templatePath: 'D:\\molde.xml', clips: [1, 3] })
    expect(scriptArgs(child(1))).toEqual(['xml', '--template', 'D:\\molde.xml', '--analysis', analysisPath, '--clips', '1,3'])
    child(1).emitStdout(jsonLine({ event: 'done', status: 'completed', stage: 'done', message: 'XML com 2 clipe(s) gravado.', outputPath: xmlPath, clips: 2 }))
    child(1).close(0)

    expect(await pending).toEqual({ ok: true, outputPath: xmlPath })
  })

  it('gerar XML: erro do Python, sem clipe e sem molde', async () => {
    const { call } = await setup()

    const pending = call<CortesXmlResult>('cortes:generate-xml', { analysisPath, templatePath: 'D:\\molde.xml', clips: [1] })
    child(0).emitStdout(
      jsonLine({ event: 'error', status: 'error', stage: 'runtime', message: 'Falha no modulo de cortes.', error: 'O molde nao tem a trilha V3.' }),
    )
    child(0).close(1)

    expect(await pending).toEqual({ ok: false, error: 'O molde nao tem a trilha V3.' })
    expect(await call('cortes:generate-xml', { analysisPath, templatePath: 'D:\\molde.xml', clips: [] })).toEqual({
      ok: false,
      error: 'Marque pelo menos um clipe.',
    })
    expect(await call('cortes:generate-xml', { analysisPath, templatePath: '', clips: [1] })).toEqual({
      ok: false,
      error: 'Escolha o molde no Inspetor.',
    })
    expect(mocks.children).toHaveLength(1)
  })
})
