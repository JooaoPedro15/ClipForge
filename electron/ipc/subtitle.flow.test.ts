// Caracterizacao do fluxo IPC da transcricao: trava o que a tela recebe em cada cenario.
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

describe('fluxo IPC da transcricao (caracterizacao)', () => {
  let root: string

  beforeEach(() => {
    root = makePythonRoot('subtitle-flow-')
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
    registerSubtitleHandlers()
    const { sent, sender } = createSender()
    const processFile = (filePath: string, options: Record<string, unknown> = {}) =>
      mocks.handlers.get('subtitle:process')?.({ sender }, filePath, options) as Promise<string>
    const cancel = (taskId: string) => mocks.handlers.get('subtitle:cancel')?.({ sender }, taskId) as Promise<boolean>
    return { sent, processFile, cancel }
  }

  function child(index: number): FakeChild {
    const found = mocks.children[index]
    if (!found) {
      throw new Error(`processo ${index} nao foi iniciado`)
    }
    return found
  }

  it('sucesso: progresso, linha de texto, traducao e conclusao', async () => {
    const { sent, processFile } = await setup()

    await processFile('C:\\videos\\aula.mp4', { maxWords: 3, translateTo: ['en'] })
    const python = child(0)
    const status = jsonLine({ event: 'status', status: 'preparing', stage: 'loading-model', message: 'Carregando modelo large-v3...', progress: 12 })
    // Linha JSON chegando em 2 pedacos: o buffer tem que juntar.
    python.emitStdout(status.slice(0, 20))
    python.emitStdout(status.slice(20))
    python.emitStdout('Idioma detectado: pt\n')
    python.emitStdout(jsonLine({ event: 'translation-done', status: 'completed', stage: 'translating', message: 'Traducao para en concluida.', targetLang: 'en', outputPath: 'C:\\videos\\aula.en.srt' }))
    python.emitStdout(jsonLine({ event: 'done', status: 'completed', stage: 'done', message: 'Transcricao concluida.', progress: 100, outputPath: 'C:\\videos\\aula.srt', durationSec: 3.2 }))
    python.close(0)
    await flush()

    expect(spawnSummary(python, root)).toMatchInlineSnapshot(`
      {
        "args": [
          "C:\\videos\\aula.mp4",
          "--model",
          "large-v3",
          "--language",
          "pt",
          "--beam-size",
          "5",
          "--max-width",
          "42",
          "--max-words",
          "3",
          "--translate-to",
          "en",
        ],
        "command": ".venv\\Scripts\\python.exe",
        "cwdIsRoot": true,
        "ioEncoding": "utf-8",
        "script": "subtitle_service.py",
        "unbuffered": "1",
      }
    `)
    expect(project(sent)).toMatchInlineSnapshot(`
      [
        {
          "ch": "subtitle:progress",
          "fileName": "aula.mp4",
          "message": "Aguardando inicializacao...",
          "queuePosition": 1,
          "stage": "queued",
          "status": "queued",
        },
        {
          "ch": "subtitle:progress",
          "fileName": "aula.mp4",
          "message": "Aguardando inicializacao...",
          "queuePosition": 1,
          "stage": "queued",
          "status": "queued",
        },
        {
          "ch": "subtitle:progress",
          "fileName": "aula.mp4",
          "message": "Inicializando SubtitleForge...",
          "progress": 5,
          "stage": "starting",
          "status": "preparing",
        },
        {
          "ch": "subtitle:progress",
          "fileName": "aula.mp4",
          "message": "Carregando modelo large-v3...",
          "progress": 12,
          "stage": "loading-model",
          "status": "preparing",
        },
        {
          "ch": "subtitle:progress",
          "fileName": "aula.mp4",
          "message": "Idioma detectado: pt",
          "stage": "log",
          "status": "preparing",
        },
        {
          "ch": "subtitle:progress",
          "fileName": "aula.mp4",
          "message": "Traducao para en concluida.",
          "stage": "translating",
          "status": "preparing",
          "translatedOutputs": {
            "en": "C:\\videos\\aula.en.srt",
          },
        },
        {
          "ch": "subtitle:done",
          "durationSec": 3.2,
          "fileName": "aula.mp4",
          "message": "Transcricao concluida.",
          "outputPath": "C:\\videos\\aula.srt",
          "progress": 100,
          "stage": "done",
          "status": "completed",
          "translatedOutputs": {
            "en": "C:\\videos\\aula.en.srt",
          },
        },
      ]
    `)
  })

  it('dois arquivos: o segundo espera na fila e comeca quando o primeiro termina', async () => {
    const { sent, processFile } = await setup()

    await processFile('C:\\videos\\a.mp4')
    await processFile('C:\\videos\\b.mp4')
    expect(mocks.children).toHaveLength(1)

    child(0).emitStdout(jsonLine({ event: 'done', status: 'completed', stage: 'done', message: 'Transcricao concluida.', durationSec: 1 }))
    child(0).close(0)
    await flush()

    expect(mocks.children).toHaveLength(2)
    expect(project(sent)).toMatchInlineSnapshot(`
      [
        {
          "ch": "subtitle:progress",
          "fileName": "a.mp4",
          "message": "Aguardando inicializacao...",
          "queuePosition": 1,
          "stage": "queued",
          "status": "queued",
        },
        {
          "ch": "subtitle:progress",
          "fileName": "a.mp4",
          "message": "Aguardando inicializacao...",
          "queuePosition": 1,
          "stage": "queued",
          "status": "queued",
        },
        {
          "ch": "subtitle:progress",
          "fileName": "a.mp4",
          "message": "Inicializando SubtitleForge...",
          "progress": 5,
          "stage": "starting",
          "status": "preparing",
        },
        {
          "ch": "subtitle:progress",
          "fileName": "b.mp4",
          "message": "Na fila (1)",
          "queuePosition": 1,
          "stage": "queued",
          "status": "queued",
        },
        {
          "ch": "subtitle:progress",
          "fileName": "b.mp4",
          "message": "Na fila (1)",
          "queuePosition": 1,
          "stage": "queued",
          "status": "queued",
        },
        {
          "ch": "subtitle:done",
          "durationSec": 1,
          "fileName": "a.mp4",
          "message": "Transcricao concluida.",
          "progress": 100,
          "stage": "done",
          "status": "completed",
        },
        {
          "ch": "subtitle:progress",
          "fileName": "b.mp4",
          "message": "Aguardando inicializacao...",
          "queuePosition": 1,
          "stage": "queued",
          "status": "queued",
        },
        {
          "ch": "subtitle:progress",
          "fileName": "b.mp4",
          "message": "Inicializando SubtitleForge...",
          "progress": 5,
          "stage": "starting",
          "status": "preparing",
        },
      ]
    `)
  })

  it('falha de CUDA: tenta de novo em CPU', async () => {
    const { sent, processFile } = await setup()

    await processFile('C:\\videos\\aula.mp4')
    child(0).emitStderr('Could not load library cublas64_12.dll\n')
    child(0).close(1)
    await flush()

    expect(child(1).args).toContain('--cpu')
    expect(project(sent)).toMatchInlineSnapshot(`
      [
        {
          "ch": "subtitle:progress",
          "fileName": "aula.mp4",
          "message": "Aguardando inicializacao...",
          "queuePosition": 1,
          "stage": "queued",
          "status": "queued",
        },
        {
          "ch": "subtitle:progress",
          "fileName": "aula.mp4",
          "message": "Aguardando inicializacao...",
          "queuePosition": 1,
          "stage": "queued",
          "status": "queued",
        },
        {
          "ch": "subtitle:progress",
          "fileName": "aula.mp4",
          "message": "Inicializando SubtitleForge...",
          "progress": 5,
          "stage": "starting",
          "status": "preparing",
        },
        {
          "ch": "subtitle:progress",
          "fileName": "aula.mp4",
          "message": "CUDA indisponivel. Tentando novamente em CPU...",
          "queuePosition": 1,
          "stage": "retrying-cpu",
          "status": "queued",
        },
        {
          "ch": "subtitle:progress",
          "fileName": "aula.mp4",
          "message": "Aguardando inicializacao...",
          "queuePosition": 1,
          "stage": "queued",
          "status": "queued",
        },
        {
          "ch": "subtitle:progress",
          "fileName": "aula.mp4",
          "message": "Inicializando SubtitleForge...",
          "progress": 5,
          "stage": "starting",
          "status": "preparing",
        },
      ]
    `)
  })

  it('erro estruturado do runner vira subtitle:error', async () => {
    const { sent, processFile } = await setup()

    await processFile('C:\\videos\\aula.mp4')
    child(0).emitStdout(jsonLine({ event: 'error', status: 'error', stage: 'runtime', message: 'Falha durante a transcricao.', error: 'arquivo corrompido' }))
    child(0).close(1)
    await flush()

    expect(mocks.children).toHaveLength(1)
    expect(project(sent)).toMatchInlineSnapshot(`
      [
        {
          "ch": "subtitle:progress",
          "fileName": "aula.mp4",
          "message": "Aguardando inicializacao...",
          "queuePosition": 1,
          "stage": "queued",
          "status": "queued",
        },
        {
          "ch": "subtitle:progress",
          "fileName": "aula.mp4",
          "message": "Aguardando inicializacao...",
          "queuePosition": 1,
          "stage": "queued",
          "status": "queued",
        },
        {
          "ch": "subtitle:progress",
          "fileName": "aula.mp4",
          "message": "Inicializando SubtitleForge...",
          "progress": 5,
          "stage": "starting",
          "status": "preparing",
        },
        {
          "ch": "subtitle:error",
          "error": "arquivo corrompido",
          "fileName": "aula.mp4",
          "message": "arquivo corrompido",
          "stage": "error",
          "status": "error",
        },
      ]
    `)
  })

  it('cancelar a tarefa ativa mata o processo', async () => {
    const { sent, processFile, cancel } = await setup()

    const taskId = await processFile('C:\\videos\\aula.mp4')
    expect(await cancel(taskId)).toBe(true)
    expect(child(0).killed).toBe(true)
    child(0).close(null)
    await flush()

    expect(project(sent)).toMatchInlineSnapshot(`
      [
        {
          "ch": "subtitle:progress",
          "fileName": "aula.mp4",
          "message": "Aguardando inicializacao...",
          "queuePosition": 1,
          "stage": "queued",
          "status": "queued",
        },
        {
          "ch": "subtitle:progress",
          "fileName": "aula.mp4",
          "message": "Aguardando inicializacao...",
          "queuePosition": 1,
          "stage": "queued",
          "status": "queued",
        },
        {
          "ch": "subtitle:progress",
          "fileName": "aula.mp4",
          "message": "Inicializando SubtitleForge...",
          "progress": 5,
          "stage": "starting",
          "status": "preparing",
        },
        {
          "ch": "subtitle:progress",
          "fileName": "aula.mp4",
          "message": "Cancelando transcricao...",
          "stage": "cancelling",
          "status": "cancelled",
        },
        {
          "ch": "subtitle:error",
          "error": "Processo cancelado pelo usuario.",
          "fileName": "aula.mp4",
          "message": "Processo cancelado pelo usuario.",
          "progress": 0,
          "stage": "cancelled",
          "status": "cancelled",
        },
      ]
    `)
  })

  it('cancelar uma tarefa que ainda esta na fila', async () => {
    const { sent, processFile, cancel } = await setup()

    await processFile('C:\\videos\\a.mp4')
    const queuedId = await processFile('C:\\videos\\b.mp4')
    expect(await cancel(queuedId)).toBe(true)

    expect(mocks.children).toHaveLength(1)
    expect(project(sent)).toMatchInlineSnapshot(`
      [
        {
          "ch": "subtitle:progress",
          "fileName": "a.mp4",
          "message": "Aguardando inicializacao...",
          "queuePosition": 1,
          "stage": "queued",
          "status": "queued",
        },
        {
          "ch": "subtitle:progress",
          "fileName": "a.mp4",
          "message": "Aguardando inicializacao...",
          "queuePosition": 1,
          "stage": "queued",
          "status": "queued",
        },
        {
          "ch": "subtitle:progress",
          "fileName": "a.mp4",
          "message": "Inicializando SubtitleForge...",
          "progress": 5,
          "stage": "starting",
          "status": "preparing",
        },
        {
          "ch": "subtitle:progress",
          "fileName": "b.mp4",
          "message": "Na fila (1)",
          "queuePosition": 1,
          "stage": "queued",
          "status": "queued",
        },
        {
          "ch": "subtitle:progress",
          "fileName": "b.mp4",
          "message": "Na fila (1)",
          "queuePosition": 1,
          "stage": "queued",
          "status": "queued",
        },
        {
          "ch": "subtitle:error",
          "error": "Tarefa removida da fila.",
          "fileName": "b.mp4",
          "message": "Tarefa removida da fila.",
          "progress": 0,
          "stage": "cancelled",
          "status": "cancelled",
        },
      ]
    `)
  })
})
