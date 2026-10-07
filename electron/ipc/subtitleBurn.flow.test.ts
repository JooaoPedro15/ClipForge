// Caracterizacao do fluxo IPC da queima (hardsub), que parte de uma transcricao concluida.
import { rmSync } from 'node:fs'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { FakeChild } from '../testing/fakeChildProcess'
import { createSender, flush, jsonLine, makePythonRoot, project, spawnSummary } from '../testing/ipcHarness'

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

const BURN_KEYS = ['mode', 'format', 'status', 'stage', 'message', 'progress', 'outputPath', 'error']

describe('fluxo IPC da queima (caracterizacao)', () => {
  let root: string

  beforeEach(() => {
    root = makePythonRoot('burn-flow-')
    vi.stubEnv('CLIPFORGE_SUBTITLE_FORGE_PATH', root)
    mocks.handlers.clear()
    mocks.children.length = 0
    vi.resetModules()
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    rmSync(root, { recursive: true, force: true })
  })

  async function setup() {
    const { registerSubtitleHandlers } = await import('./subtitle.js')
    const { registerHardsubHandlers } = await import('./subtitleBurn.js')
    registerSubtitleHandlers()
    registerHardsubHandlers()
    const { sent, sender } = createSender()
    const transcribe = (filePath: string, options: Record<string, unknown> = {}) =>
      mocks.handlers.get('subtitle:process')?.({ sender }, filePath, options) as Promise<string>
    const burn = (taskId: string, mode: string, format: string) =>
      mocks.handlers.get('subtitle:burn')?.({ sender }, taskId, mode, format) as Promise<string>
    return { sent, transcribe, burn }
  }

  function child(index: number): FakeChild {
    const found = mocks.children[index]
    if (!found) {
      throw new Error(`processo ${index} nao foi iniciado`)
    }
    return found
  }

  it('queima a partir de uma transcricao concluida', async () => {
    const { sent, transcribe, burn } = await setup()

    const taskId = await transcribe('C:\\videos\\aula.mp4', { videoType: 'gameplay de terror' })
    child(0).emitStdout(jsonLine({ event: 'done', status: 'completed', stage: 'done', message: 'Transcricao concluida.', outputPath: 'C:\\videos\\aula.srt', detectedLanguage: 'pt', durationSec: 1 }))
    child(0).close(0)
    await flush()
    sent.length = 0

    await burn(taskId, 'zh-en', 'long')
    const python = child(1)
    python.emitStdout(jsonLine({ event: 'status', status: 'processing', stage: 'burning', message: 'Queimando legenda...', progress: 60 }))
    python.emitStdout('linha de log solta do ffmpeg\n')
    python.emitStdout(jsonLine({ event: 'done', status: 'completed', stage: 'done', message: 'Queima concluida.', outputPath: 'C:\\videos\\aula.hardsub.zh-en.mp4' }))
    python.close(0)
    await flush()

    expect(spawnSummary(python, root)).toMatchInlineSnapshot(`
      {
        "args": [
          "--video",
          "C:\\videos\\aula.mp4",
          "--original-srt",
          "C:\\videos\\aula.srt",
          "--source-language",
          "pt",
          "--mode",
          "zh-en",
          "--format",
          "long",
          "--video-type",
          "gameplay de terror",
        ],
        "command": ".venv\\Scripts\\python.exe",
        "cwdIsRoot": true,
        "ioEncoding": "utf-8",
        "script": "hardsub_service.py",
        "unbuffered": "1",
      }
    `)
    expect(project(sent, BURN_KEYS)).toMatchInlineSnapshot(`
      [
        {
          "ch": "subtitle:burn-progress",
          "format": "long",
          "message": "Job de queima adicionado a fila.",
          "mode": "zh-en",
          "stage": "queued",
          "status": "queued",
        },
        {
          "ch": "subtitle:burn-progress",
          "format": "long",
          "message": "Preparando queima...",
          "mode": "zh-en",
          "progress": 5,
          "stage": "starting",
          "status": "preparing",
        },
        {
          "ch": "subtitle:burn-progress",
          "format": "long",
          "message": "Queimando legenda...",
          "mode": "zh-en",
          "progress": 60,
          "stage": "burning",
          "status": "processing",
        },
        {
          "ch": "subtitle:burn-done",
          "format": "long",
          "message": "Queima concluida.",
          "mode": "zh-en",
          "outputPath": "C:\\videos\\aula.hardsub.zh-en.mp4",
          "progress": 100,
          "stage": "done",
          "status": "completed",
        },
      ]
    `)
  })

  it('queima sem transcricao concluida da erro sem iniciar processo', async () => {
    const { sent, burn } = await setup()

    await burn('tarefa-que-nao-existe', 'zh', 'shorts')

    expect(mocks.children).toHaveLength(0)
    expect(project(sent, BURN_KEYS)).toMatchInlineSnapshot(`
      [
        {
          "ch": "subtitle:burn-progress",
          "format": "shorts",
          "message": "Job de queima adicionado a fila.",
          "mode": "zh",
          "stage": "queued",
          "status": "queued",
        },
        {
          "ch": "subtitle:burn-error",
          "error": "Tarefa de transcricao nao encontrada ou sem srt gerado.",
          "format": "shorts",
          "message": "Job de queima adicionado a fila.",
          "mode": "zh",
          "stage": "error",
          "status": "error",
        },
      ]
    `)
  })

  it('erro do runner da queima vira subtitle:burn-error', async () => {
    const { sent, transcribe, burn } = await setup()

    const taskId = await transcribe('C:\\videos\\aula.mp4')
    child(0).emitStdout(jsonLine({ event: 'done', status: 'completed', stage: 'done', message: 'Transcricao concluida.', outputPath: 'C:\\videos\\aula.srt', durationSec: 1 }))
    child(0).close(0)
    await flush()
    sent.length = 0

    await burn(taskId, 'zh', 'shorts')
    child(1).emitStdout(jsonLine({ event: 'error', status: 'error', stage: 'burning', message: 'Falha ao queimar.', error: 'ffmpeg saiu com codigo 1' }))
    child(1).close(1)
    await flush()

    expect(project(sent, BURN_KEYS)).toMatchInlineSnapshot(`
      [
        {
          "ch": "subtitle:burn-progress",
          "format": "shorts",
          "message": "Job de queima adicionado a fila.",
          "mode": "zh",
          "stage": "queued",
          "status": "queued",
        },
        {
          "ch": "subtitle:burn-progress",
          "format": "shorts",
          "message": "Preparando queima...",
          "mode": "zh",
          "progress": 5,
          "stage": "starting",
          "status": "preparing",
        },
        {
          "ch": "subtitle:burn-error",
          "error": "ffmpeg saiu com codigo 1",
          "format": "shorts",
          "message": "Falha ao queimar.",
          "mode": "zh",
          "stage": "error",
          "status": "error",
        },
      ]
    `)
  })
})
