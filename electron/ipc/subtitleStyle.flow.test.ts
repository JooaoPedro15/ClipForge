// IPC do aprendizado de estilo: argumentos, leitura da biblioteca e "ensinar" como job da fila de GPU.
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { FakeChild } from '../testing/fakeChildProcess'
import { createSender, flush, jsonLine, makePythonRoot } from '../testing/ipcHarness'

const mocks = vi.hoisted(() => ({
  handlers: new Map<string, (...args: unknown[]) => unknown>(),
  children: [] as FakeChild[],
  userData: '',
}))

vi.mock('electron', () => ({
  app: { getPath: () => mocks.userData },
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

const REQUEST = {
  originalPath: 'C:\\videos\\aula.mp4',
  srtPath: 'C:\\videos\\aula-corrigida.srt',
  finalPath: 'C:\\videos\\aula-final.mp4',
  model: 'large-v3',
  language: 'pt',
  useCpu: true,
}

describe('IPC do aprendizado de estilo', () => {
  let root: string

  beforeEach(() => {
    root = makePythonRoot('style-forge-')
    mocks.userData = mkdtempSync(path.join(tmpdir(), 'style-userdata-'))
    vi.stubEnv('CLIPFORGE_SUBTITLE_FORGE_PATH', root)
    mocks.handlers.clear()
    mocks.children.length = 0
    vi.resetModules()
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    rmSync(root, { recursive: true, force: true })
    rmSync(mocks.userData, { recursive: true, force: true })
  })

  async function setup() {
    const style = await import('./subtitleStyle.js')
    const { registerSubtitleHandlers } = await import('./subtitle.js')
    style.registerSubtitleStyleHandlers()
    registerSubtitleHandlers()
    const { sent, sender } = createSender()
    const call = <T>(channel: string, ...args: unknown[]) => mocks.handlers.get(channel)?.({ sender }, ...args) as Promise<T>
    return { style, sent, call }
  }

  function child(index: number): FakeChild {
    const found = mocks.children[index]
    if (!found) {
      throw new Error(`processo ${index} nao foi iniciado`)
    }
    return found
  }

  it('monta os argumentos do learn e do forget', async () => {
    const { style } = await setup()

    expect(style.buildStyleLearnArgs(REQUEST, 'C:\\store')).toEqual([
      'learn',
      '--original',
      'C:\\videos\\aula.mp4',
      '--srt',
      'C:\\videos\\aula-corrigida.srt',
      '--final',
      'C:\\videos\\aula-final.mp4',
      '--store',
      'C:\\store',
      '--model',
      'large-v3',
      '--language',
      'pt',
      '--cpu',
    ])
    expect(style.buildStyleForgetArgs('abc', 'C:\\store')).toEqual(['forget', '--id', 'abc', '--store', 'C:\\store'])
  })

  it('le a biblioteca e os perfis direto dos arquivos', async () => {
    const { style } = await setup()
    const store = path.join(mocks.userData, 'subtitle-style')
    mkdirSync(path.join(store, 'profiles', 'vertical'), { recursive: true })
    writeFileSync(path.join(store, 'library.json'), JSON.stringify({ version: 1, videos: [{ id: 'abc', profile: 'vertical', name: 'aula.mp4' }] }))
    writeFileSync(path.join(store, 'profiles', 'vertical', 'params.json'), JSON.stringify({ videos: 1, lead_in_ms: 80 }))
    writeFileSync(path.join(store, 'profiles', 'vertical', 'tree.txt'), '|--- pausa_ms <= 180.00')

    const library = style.readStyleLibrary(store)

    expect(library.videos.map((video) => video.id)).toEqual(['abc'])
    expect(library.profiles.vertical?.params.lead_in_ms).toBe(80)
    expect(library.profiles.vertical?.tree).toContain('pausa_ms')
    expect(library.profiles.horizontal).toBeUndefined()
    expect(library.minVideos).toBe(3)
    expect(style.readStyleLibrary(path.join(mocks.userData, 'nao-existe'))).toEqual({ videos: [], profiles: {}, minVideos: 3 })
  })

  it('ensinar espera a transcricao em andamento, repassa o progresso e devolve o relatorio', async () => {
    const { sent, call } = await setup()

    await call<string>('subtitle:process', 'C:\\videos\\outra.mp4')
    const learning = call<{ ok: boolean; report?: unknown }>('subtitleStyle:learn', REQUEST)
    expect(mocks.children).toHaveLength(1)

    child(0).emitStdout(jsonLine({ event: 'done', status: 'completed', stage: 'done', message: 'ok', durationSec: 1 }))
    child(0).close(0)
    await flush()

    const python = child(1)
    expect(python.args[0]).toMatch(/style_service\.py$/)
    expect(python.args.slice(1, 2)).toEqual(['learn'])
    expect(python.args).toContain(path.join(mocks.userData, 'subtitle-style'))

    python.emitStdout(jsonLine({ event: 'status', status: 'processing', stage: 'training', message: 'Treinando o seu estilo...', progress: 90 }))
    python.emitStdout(jsonLine({ event: 'done', status: 'completed', stage: 'done', message: 'Estilo atualizado.', report: { profile: 'horizontal', f1Formula: 0.5 } }))
    python.close(0)

    await expect(learning).resolves.toEqual({ ok: true, report: { profile: 'horizontal', f1Formula: 0.5 } })
    expect(sent.filter(([channel]) => channel === 'subtitleStyle:progress').map(([, payload]) => payload.message)).toEqual([
      'Na fila (1)',
      'Aguardando inicializacao...',
      'Treinando o seu estilo...',
    ])
  })

  it('erro do python vira ok:false com a mensagem pra tela', async () => {
    const { call } = await setup()

    const learning = call<{ ok: boolean; error?: string }>('subtitleStyle:learn', REQUEST)
    child(0).emitStdout(jsonLine({ event: 'error', status: 'error', stage: 'style', message: 'SRT de outro video.', error: 'O SRT corrigido nao parece ser desse video.' }))
    child(0).close(1)

    await expect(learning).resolves.toEqual({ ok: false, error: 'O SRT corrigido nao parece ser desse video.' })
  })

  it('esquecer roda direto, sem esperar a fila de GPU', async () => {
    const { call } = await setup()

    await call<string>('subtitle:process', 'C:\\videos\\outra.mp4')
    const forgetting = call<{ ok: boolean }>('subtitleStyle:forget', 'abc')

    expect(mocks.children).toHaveLength(2)
    const python = child(1)
    expect(python.args.slice(1)).toEqual(['forget', '--id', 'abc', '--store', path.join(mocks.userData, 'subtitle-style')])
    python.emitStdout(jsonLine({ event: 'done', status: 'completed', stage: 'done', message: 'ok', report: { videoId: 'abc', profile: 'vertical' } }))
    python.close(0)

    await expect(forgetting).resolves.toEqual({ ok: true, report: { videoId: 'abc', profile: 'vertical' } })
  })
})
