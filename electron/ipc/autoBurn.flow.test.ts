// Entrada "Versao em chines": o video sai traduzido e queimado sem clique no meio.
import { rmSync } from 'node:fs'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { FakeChild } from '../testing/fakeChildProcess'
import { createSender, flush, jsonLine, makePythonRoot } from '../testing/ipcHarness'

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

const done = jsonLine({ event: 'done', status: 'completed', stage: 'done', message: 'ok', durationSec: 1, outputPath: 'C:\\videos\\final.srt' })

describe('queima automatica depois da transcricao', () => {
  let forgeRoot: string

  beforeEach(() => {
    forgeRoot = makePythonRoot('autoburn-')
    vi.stubEnv('CLIPFORGE_SUBTITLE_FORGE_PATH', forgeRoot)
    mocks.handlers.clear()
    mocks.children.length = 0
    vi.resetModules()
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    rmSync(forgeRoot, { recursive: true, force: true })
  })

  async function setup() {
    const { registerSubtitleHandlers } = await import('./subtitle.js')
    const { registerHardsubHandlers } = await import('./subtitleBurn.js')
    registerSubtitleHandlers()
    registerHardsubHandlers()
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

  it('com autoBurn a queima entra na fila sozinha, no modo e formato pedidos', async () => {
    const { sent, call } = await setup()

    await call<string>('subtitle:process', 'C:\\videos\\final.mp4', { autoBurn: 'zh', format: 'shorts' })
    child(0).emitStdout(done)
    child(0).close(0)
    await flush()

    expect(mocks.children).toHaveLength(2)
    const burnArgs = child(1).args
    expect(burnArgs[0]).toMatch(/hardsub_service\.py$/)
    expect(burnArgs.slice(burnArgs.indexOf('--mode'), burnArgs.indexOf('--mode') + 4)).toEqual(['--mode', 'zh', '--format', 'shorts'])

    // A tela recebe o pedido em cada evento da tarefa (pra mostrar "Versao em chines").
    const doneEvent = sent.find(([channel]) => channel === 'subtitle:done')
    expect(doneEvent?.[1].autoBurn).toBe('zh')
    expect(sent.some(([channel, payload]) => channel === 'subtitle:burn-progress' && payload.mode === 'zh')).toBe(true)
  })

  it('sem autoBurn a transcricao termina e nada mais roda', async () => {
    const { call } = await setup()

    await call<string>('subtitle:process', 'C:\\videos\\bruto.mp4')
    child(0).emitStdout(done)
    child(0).close(0)
    await flush()

    expect(mocks.children).toHaveLength(1)
  })

  it('transcricao com erro nao queima', async () => {
    const { call } = await setup()

    await call<string>('subtitle:process', 'C:\\videos\\final.mp4', { autoBurn: 'zh' })
    child(0).emitStdout(jsonLine({ event: 'error', status: 'error', stage: 'runtime', message: 'falhou', error: 'arquivo corrompido' }))
    child(0).close(1)
    await flush()

    expect(mocks.children).toHaveLength(1)
  })

  it('pedido que nao e de queima (traduzir de novo) e ignorado', async () => {
    const { call } = await setup()

    await call<string>('subtitle:process', 'C:\\videos\\final.mp4', { autoBurn: 'translate-zh' })
    child(0).emitStdout(done)
    child(0).close(0)
    await flush()

    expect(mocks.children).toHaveLength(1)
  })
})
