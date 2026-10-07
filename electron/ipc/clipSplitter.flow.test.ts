// Caracterizacao do fluxo IPC do Pre-Editor: trava o que a tela recebe em cada cenario.
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

describe('fluxo IPC do Pre-Editor (caracterizacao)', () => {
  let root: string

  beforeEach(() => {
    root = makePythonRoot('clip-flow-')
    vi.stubEnv('CLIPFORGE_CLIP_SPLITTER_PATH', root)
    mocks.handlers.clear()
    mocks.children.length = 0
    vi.resetModules()
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    rmSync(root, { recursive: true, force: true })
  })

  async function setup() {
    const { registerClipSplitterHandlers } = await import('./clipSplitter.js')
    registerClipSplitterHandlers()
    const { sent, sender } = createSender()
    const processFile = (sourcePath: string, options: Record<string, unknown> = {}) =>
      mocks.handlers.get('clipSplitter:process')?.({ sender }, sourcePath, options) as Promise<string>
    const cancel = (taskId: string) => mocks.handlers.get('clipSplitter:cancel')?.({ sender }, taskId) as Promise<boolean>
    return { sent, processFile, cancel }
  }

  function child(index: number): FakeChild {
    const found = mocks.children[index]
    if (!found) {
      throw new Error(`processo ${index} nao foi iniciado`)
    }
    return found
  }

  it('sucesso: progresso, saida em texto e video limpo', async () => {
    const { sent, processFile } = await setup()

    await processFile('D:\\brutos\\live.mp4', { preEditMode: 'aggressive', writeDebugJson: true })
    const python = child(0)
    python.emitStdout(jsonLine({ event: 'status', status: 'processing', stage: 'transcribing', message: 'Transcrevendo audio...', progress: 30, sourceDurationSec: 600 }))
    python.emitStdout('Pasta de saida: D:\\brutos\\live_preedit\n')
    python.emitStdout(
      jsonLine({
        event: 'done',
        status: 'completed',
        stage: 'done',
        message: 'Pre-edicao concluida.',
        progress: 100,
        clipsCreated: 1,
        totalClips: 1,
        durationSec: 42,
        clips: [{ clipId: 'c1', index: 1, filePath: 'D:\\brutos\\live_preedit\\live_preedit.mp4', fileName: 'live_preedit.mp4', startSec: 0, endSec: 540, durationSec: 540, reason: 'Pre-edicao unica', transcriptSnippet: 'Video limpo' }],
      }),
    )
    python.close(0)
    await flush()

    expect(spawnSummary(python, root)).toMatchInlineSnapshot(`
      {
        "args": [
          "D:\\brutos\\live.mp4",
          "--project-root",
          "C:\\Users\\JOO~1\\AppData\\Local\\Temp\\clip-flow-ADyeXq",
          "--mode",
          "silence",
          "--preedit-mode",
          "aggressive",
          "--target-duration",
          "35",
          "--min-duration",
          "20",
          "--max-duration",
          "50",
          "--silence-threshold-db",
          "-35",
          "--silence-min-duration",
          "0.45",
          "--analysis-audio-track",
          "1",
          "--write-debug-json",
        ],
        "command": ".venv\\Scripts\\python.exe",
        "cwdIsRoot": true,
        "ioEncoding": "utf-8",
        "script": "clip_splitter_service.py",
        "unbuffered": "1",
      }
    `)
    expect(project(sent)).toMatchInlineSnapshot(`
      [
        {
          "ch": "clipSplitter:progress",
          "clipsCreated": 0,
          "message": "Aguardando inicializacao...",
          "mode": "silence",
          "queuePosition": 1,
          "sourceName": "live.mp4",
          "stage": "queued",
          "status": "queued",
        },
        {
          "ch": "clipSplitter:progress",
          "clipsCreated": 0,
          "message": "Aguardando inicializacao...",
          "mode": "silence",
          "queuePosition": 1,
          "sourceName": "live.mp4",
          "stage": "queued",
          "status": "queued",
        },
        {
          "ch": "clipSplitter:progress",
          "clipsCreated": 0,
          "message": "Inicializando Pre-Editor em modo local...",
          "mode": "silence",
          "progress": 5,
          "sourceName": "live.mp4",
          "stage": "starting",
          "status": "preparing",
        },
        {
          "ch": "clipSplitter:progress",
          "clipsCreated": 0,
          "message": "Transcrevendo audio...",
          "mode": "silence",
          "progress": 30,
          "sourceName": "live.mp4",
          "stage": "transcribing",
          "status": "processing",
        },
        {
          "ch": "clipSplitter:progress",
          "clipsCreated": 0,
          "message": "Pasta de saida: D:\\brutos\\live_preedit",
          "mode": "silence",
          "outputDir": "D:\\brutos\\live_preedit",
          "sourceName": "live.mp4",
          "stage": "log",
          "status": "processing",
        },
        {
          "ch": "clipSplitter:done",
          "clipsCreated": 1,
          "durationSec": 42,
          "message": "Pre-edicao concluida.",
          "mode": "silence",
          "outputDir": "D:\\brutos\\live_preedit",
          "progress": 100,
          "sourceName": "live.mp4",
          "stage": "done",
          "status": "completed",
          "totalClips": 1,
        },
      ]
    `)
  })

  it('crash nativo de GPU: tenta em CPU e, se cair de novo, explica o codigo', async () => {
    const { sent, processFile } = await setup()

    await processFile('D:\\brutos\\live.mp4')
    child(0).close(3221226505)
    await flush()
    expect(child(1).args).toContain('--cpu')

    child(1).close(3221225477)
    await flush()

    expect(mocks.children).toHaveLength(2)
    expect(project(sent)).toMatchInlineSnapshot(`
      [
        {
          "ch": "clipSplitter:progress",
          "clipsCreated": 0,
          "message": "Aguardando inicializacao...",
          "mode": "silence",
          "queuePosition": 1,
          "sourceName": "live.mp4",
          "stage": "queued",
          "status": "queued",
        },
        {
          "ch": "clipSplitter:progress",
          "clipsCreated": 0,
          "message": "Aguardando inicializacao...",
          "mode": "silence",
          "queuePosition": 1,
          "sourceName": "live.mp4",
          "stage": "queued",
          "status": "queued",
        },
        {
          "ch": "clipSplitter:progress",
          "clipsCreated": 0,
          "message": "Inicializando Pre-Editor em modo local...",
          "mode": "silence",
          "progress": 5,
          "sourceName": "live.mp4",
          "stage": "starting",
          "status": "preparing",
        },
        {
          "ch": "clipSplitter:progress",
          "clipsCreated": 0,
          "message": "Falha no caminho CUDA. Tentando novamente em CPU...",
          "mode": "silence",
          "queuePosition": 1,
          "sourceName": "live.mp4",
          "stage": "retrying-cpu",
          "status": "queued",
        },
        {
          "ch": "clipSplitter:progress",
          "clipsCreated": 0,
          "message": "Aguardando inicializacao...",
          "mode": "silence",
          "queuePosition": 1,
          "sourceName": "live.mp4",
          "stage": "queued",
          "status": "queued",
        },
        {
          "ch": "clipSplitter:progress",
          "clipsCreated": 0,
          "message": "Inicializando Pre-Editor com Whisper em CPU...",
          "mode": "silence",
          "progress": 5,
          "sourceName": "live.mp4",
          "stage": "starting",
          "status": "preparing",
        },
        {
          "ch": "clipSplitter:error",
          "clipsCreated": 0,
          "error": "O Pre-Editor encerrou com violacao de acesso do Windows (3221225477 / 0xC0000005). Isso costuma indicar falha em biblioteca nativa, driver ou memoria da GPU.",
          "message": "O Pre-Editor encerrou com violacao de acesso do Windows (3221225477 / 0xC0000005). Isso costuma indicar falha em biblioteca nativa, driver ou memoria da GPU.",
          "mode": "silence",
          "sourceName": "live.mp4",
          "stage": "error",
          "status": "error",
        },
      ]
    `)
  })

  it('cancelar um job que ainda esta na fila', async () => {
    const { sent, processFile, cancel } = await setup()

    await processFile('D:\\brutos\\a.mp4')
    const queuedId = await processFile('D:\\brutos\\b.mp4')
    expect(await cancel(queuedId)).toBe(true)

    expect(mocks.children).toHaveLength(1)
    expect(project(sent)).toMatchInlineSnapshot(`
      [
        {
          "ch": "clipSplitter:progress",
          "clipsCreated": 0,
          "message": "Aguardando inicializacao...",
          "mode": "silence",
          "queuePosition": 1,
          "sourceName": "a.mp4",
          "stage": "queued",
          "status": "queued",
        },
        {
          "ch": "clipSplitter:progress",
          "clipsCreated": 0,
          "message": "Aguardando inicializacao...",
          "mode": "silence",
          "queuePosition": 1,
          "sourceName": "a.mp4",
          "stage": "queued",
          "status": "queued",
        },
        {
          "ch": "clipSplitter:progress",
          "clipsCreated": 0,
          "message": "Inicializando Pre-Editor em modo local...",
          "mode": "silence",
          "progress": 5,
          "sourceName": "a.mp4",
          "stage": "starting",
          "status": "preparing",
        },
        {
          "ch": "clipSplitter:progress",
          "clipsCreated": 0,
          "message": "Na fila (1)",
          "mode": "silence",
          "queuePosition": 1,
          "sourceName": "b.mp4",
          "stage": "queued",
          "status": "queued",
        },
        {
          "ch": "clipSplitter:progress",
          "clipsCreated": 0,
          "message": "Na fila (1)",
          "mode": "silence",
          "queuePosition": 1,
          "sourceName": "b.mp4",
          "stage": "queued",
          "status": "queued",
        },
        {
          "ch": "clipSplitter:error",
          "clipsCreated": 0,
          "error": "Tarefa cancelada antes de iniciar.",
          "message": "Tarefa cancelada antes de iniciar.",
          "mode": "silence",
          "sourceName": "b.mp4",
          "stage": "cancelled",
          "status": "cancelled",
        },
      ]
    `)
  })

  it('cancelar o job ativo mata o processo', async () => {
    const { sent, processFile, cancel } = await setup()

    const taskId = await processFile('D:\\brutos\\live.mp4')
    expect(await cancel(taskId)).toBe(true)
    expect(child(0).killed).toBe(true)
    child(0).close(null)
    await flush()

    expect(project(sent)).toMatchInlineSnapshot(`
      [
        {
          "ch": "clipSplitter:progress",
          "clipsCreated": 0,
          "message": "Aguardando inicializacao...",
          "mode": "silence",
          "queuePosition": 1,
          "sourceName": "live.mp4",
          "stage": "queued",
          "status": "queued",
        },
        {
          "ch": "clipSplitter:progress",
          "clipsCreated": 0,
          "message": "Aguardando inicializacao...",
          "mode": "silence",
          "queuePosition": 1,
          "sourceName": "live.mp4",
          "stage": "queued",
          "status": "queued",
        },
        {
          "ch": "clipSplitter:progress",
          "clipsCreated": 0,
          "message": "Inicializando Pre-Editor em modo local...",
          "mode": "silence",
          "progress": 5,
          "sourceName": "live.mp4",
          "stage": "starting",
          "status": "preparing",
        },
        {
          "ch": "clipSplitter:error",
          "clipsCreated": 0,
          "error": "Processo cancelado pelo usuario.",
          "message": "Processo cancelado pelo usuario.",
          "mode": "silence",
          "sourceName": "live.mp4",
          "stage": "cancelled",
          "status": "cancelled",
        },
      ]
    `)
  })
})
