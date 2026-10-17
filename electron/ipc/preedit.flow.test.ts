// Fluxo IPC da Pre-edicao que aprende: editar varios brutos, cancelar e ler a biblioteca.
import { rmSync } from 'node:fs'
import path from 'node:path'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { FakeChild } from '../testing/fakeChildProcess'
import { createSender, flush, jsonLine, makePythonRoot, project } from '../testing/ipcHarness'

const mocks = vi.hoisted(() => ({
  handlers: new Map<string, (...args: unknown[]) => unknown>(),
  children: [] as FakeChild[],
}))

vi.mock('electron', () => ({
  app: { getPath: () => 'C:\\AppData' },
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

const STORE = path.join('C:\\AppData', 'clip-forge', 'preedit-learning')
const KEYS = ['title', 'kind', 'status', 'stage', 'message', 'error']

const status = (stage: string, message: string, extra: Record<string, unknown> = {}) =>
  jsonLine({ event: 'status', status: 'processing', stage, message, ...extra })

const scriptArgs = (python: FakeChild) => python.args.slice(1)

describe('fluxo IPC da Pre-edicao que aprende', () => {
  let root: string

  beforeEach(() => {
    root = makePythonRoot('preedit-flow-')
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
    const { registerPreeditHandlers } = await import('./preedit.js')
    registerPreeditHandlers()
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

  it('editar: etapas e o caminho do XML no fim', async () => {
    const { sent, call } = await setup()
    const first = path.join(root, '2026-10-16 14-00-00.mkv')
    const second = path.join(root, '2026-10-16 14-40-00.mkv')

    await call('preedit:edit', { recordings: [first, second], minutes: 20, moldePath: '', zoomStyle: 'aproximando' })
    const python = child(0)
    expect(path.basename(python.args[0] ?? '')).toBe('preedit_service.py')
    expect(scriptArgs(python)).toEqual(['edit', '--recording', first, '--recording', second, '--minutes', '20', '--zoom-style', 'aproximando', '--store', STORE])
    expect(python.options.env?.CLIPFORGE_OLLAMA_MODEL).toBe('qwen2.5:7b-instruct')

    python.emitStdout(status('transcribing', 'Fala [1/2] 2026-10-16 14-00-00.mkv', { progress: 10 }))
    const report = { xmlPath: 'X.xml', durationSec: 600, segments: 40, zooms: 5, warnings: ['Sem molde: sem zoom.'] }
    python.emitStdout(jsonLine({ event: 'done', status: 'completed', stage: 'done', message: 'Pre-edicao pronta.', report }))
    python.close(0)
    await flush()

    expect(project(sent, ['stage']).map((event) => event.stage)).toEqual(['queued', 'queued', 'starting', 'transcribing', 'done'])
    const [channel, payload] = sent.at(-1) ?? []
    expect(channel).toBe('preedit:done')
    expect(payload).toMatchObject({ title: '2026-10-16 14-00-00.mkv +1', kind: 'edit', warnings: ['Sem molde: sem zoom.'] })
    expect(payload?.result).toMatchObject({ xmlPath: 'X.xml', zooms: 5 })
  })

  it('preedit cancel kills the job', async () => {
    const { sent, call } = await setup()

    const taskId = await call<string>('preedit:teach-finals', { projectsDir: 'P', videosDir: 'V' })
    child(0).emitStdout(status('reading-project', 'Projeto [1/438] a.prproj', { progress: 2 }))
    expect(await call('preedit:cancel', taskId)).toBe(true)
    expect(child(0).killed).toBe(true)
    child(0).close(null)
    await flush()

    expect(project(sent, KEYS).at(-1)).toEqual({
      ch: 'preedit:error',
      title: 'Ensinar com videos prontos',
      kind: 'teach-finals',
      status: 'cancelled',
      stage: 'cancelled',
      message: 'Processo cancelado pelo usuario.',
      error: 'Processo cancelado pelo usuario.',
    })
  })

  it('erro do Python chega na tela', async () => {
    const { sent, call } = await setup()

    await call('preedit:teach-projects', { projects: ['a.prproj'] })
    child(0).emitStdout(jsonLine({ event: 'error', status: 'error', stage: 'preedit', message: 'Escolha pelo menos um projeto do Premiere.', error: 'x' }))
    child(0).close(1)
    await flush()

    expect(project(sent, KEYS).at(-1)).toMatchObject({ ch: 'preedit:error', kind: 'teach-projects', status: 'error', error: 'x' })
  })

  it('biblioteca roda fora da fila e devolve o resumo', async () => {
    const { call } = await setup()

    const pending = call('preedit:library')
    const python = child(0)
    expect(scriptArgs(python)).toEqual(['report', '--store', STORE])
    const report = { sources: [{ kind: 'projeto', format: 'longo' }], models: {} }
    python.emitStdout(jsonLine({ event: 'done', status: 'completed', stage: 'done', message: 'Biblioteca do Pre-editor.', report }))
    python.close(0)

    expect(await pending).toEqual({ ok: true, library: { recordings: { longo: 1, short: 0 }, finals: { longo: 0, short: 0 }, editorReady: false } })
  })
})
