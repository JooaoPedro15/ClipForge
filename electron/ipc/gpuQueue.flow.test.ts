// Fila unica de GPU entre ferramentas: um job de um IPC espera o de outro terminar.
import { rmSync } from 'node:fs'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

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

const done = (extra: Record<string, unknown> = {}) =>
  jsonLine({ event: 'done', status: 'completed', stage: 'done', message: 'ok', durationSec: 1, ...extra })

describe('fila unica de GPU entre transcricao, queima e Pre-Editor', () => {
  let forgeRoot: string
  let clipRoot: string

  beforeEach(() => {
    forgeRoot = makePythonRoot('gpu-forge-')
    clipRoot = makePythonRoot('gpu-clip-')
    vi.stubEnv('CLIPFORGE_SUBTITLE_FORGE_PATH', forgeRoot)
    vi.stubEnv('CLIPFORGE_CLIP_SPLITTER_PATH', clipRoot)
    mocks.handlers.clear()
    mocks.children.length = 0
    vi.resetModules()
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    rmSync(forgeRoot, { recursive: true, force: true })
    rmSync(clipRoot, { recursive: true, force: true })
  })

  async function setup() {
    const { registerSubtitleHandlers } = await import('./subtitle.js')
    const { registerHardsubHandlers } = await import('./subtitleBurn.js')
    const { registerClipSplitterHandlers } = await import('./clipSplitter.js')
    registerSubtitleHandlers()
    registerHardsubHandlers()
    registerClipSplitterHandlers()
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

  it('a queima espera a transcricao em andamento terminar', async () => {
    const { sent, call } = await setup()

    const first = await call<string>('subtitle:process', 'C:\\videos\\a.mp4')
    child(0).emitStdout(done({ outputPath: 'C:\\videos\\a.srt' }))
    child(0).close(0)
    await flush()

    await call<string>('subtitle:process', 'C:\\videos\\b.mp4')
    sent.length = 0
    await call<string>('subtitle:burn', first, 'zh', 'shorts')

    // A transcricao de b.mp4 ainda roda: a queima nao pode subir outro processo na GPU.
    expect(mocks.children).toHaveLength(2)

    child(1).emitStdout(done({ outputPath: 'C:\\videos\\b.srt' }))
    child(1).close(0)
    await flush()

    expect(mocks.children).toHaveLength(3)
    expect(child(2).args[0]).toMatch(/hardsub_service\.py$/)
    expect(project(sent, ['fileName', 'mode', 'status', 'stage', 'message', 'queuePosition'])).toMatchInlineSnapshot(`
      [
        {
          "ch": "subtitle:burn-progress",
          "message": "Job de queima adicionado a fila.",
          "mode": "zh",
          "stage": "queued",
          "status": "queued",
        },
        {
          "ch": "subtitle:burn-progress",
          "message": "Na fila (1)",
          "mode": "zh",
          "stage": "queued",
          "status": "queued",
        },
        {
          "ch": "subtitle:done",
          "fileName": "b.mp4",
          "message": "ok",
          "stage": "done",
          "status": "completed",
        },
        {
          "ch": "subtitle:burn-progress",
          "message": "Preparando queima...",
          "mode": "zh",
          "stage": "starting",
          "status": "preparing",
        },
      ]
    `)
  })

  it('o Pre-Editor entra na mesma fila e mostra a posicao global', async () => {
    const { sent, call } = await setup()

    await call<string>('subtitle:process', 'C:\\videos\\a.mp4')
    sent.length = 0
    await call<string>('clipSplitter:process', 'D:\\brutos\\live.mp4')

    expect(mocks.children).toHaveLength(1)

    child(0).emitStdout(done({ outputPath: 'C:\\videos\\a.srt' }))
    child(0).close(0)
    await flush()

    expect(mocks.children).toHaveLength(2)
    expect(child(1).args[0]).toMatch(/clip_splitter_service\.py$/)
    expect(project(sent, ['fileName', 'sourceName', 'status', 'stage', 'message', 'queuePosition'])).toMatchInlineSnapshot(`
      [
        {
          "ch": "clipSplitter:progress",
          "message": "Na fila (1)",
          "queuePosition": 1,
          "sourceName": "live.mp4",
          "stage": "queued",
          "status": "queued",
        },
        {
          "ch": "clipSplitter:progress",
          "message": "Na fila (1)",
          "queuePosition": 1,
          "sourceName": "live.mp4",
          "stage": "queued",
          "status": "queued",
        },
        {
          "ch": "subtitle:done",
          "fileName": "a.mp4",
          "message": "ok",
          "stage": "done",
          "status": "completed",
        },
        {
          "ch": "clipSplitter:progress",
          "message": "Aguardando inicializacao...",
          "queuePosition": 1,
          "sourceName": "live.mp4",
          "stage": "queued",
          "status": "queued",
        },
        {
          "ch": "clipSplitter:progress",
          "message": "Inicializando Pre-Editor em modo local...",
          "sourceName": "live.mp4",
          "stage": "starting",
          "status": "preparing",
        },
      ]
    `)
  })
})
