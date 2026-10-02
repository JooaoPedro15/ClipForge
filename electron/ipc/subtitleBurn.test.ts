import { afterEach, describe, expect, it, vi } from 'vitest'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

vi.mock('electron', () => ({
  ipcMain: {
    handle: vi.fn(),
  },
}))

vi.mock('./subtitle.js', () => ({
  resolveSubtitleForgeRoot: vi.fn(),
  resolvePythonCommand: vi.fn(),
  resolveNvidiaBinPaths: vi.fn(),
  getSubtitleTaskSnapshot: vi.fn(),
}))

import { buildHardsubProcessArgs, parseHardsubRunnerEvent, resolveHardsubScriptPath } from './subtitleBurn.js'

describe('resolveHardsubScriptPath', () => {
  let tempRoot: string | null = null

  afterEach(() => {
    if (tempRoot) {
      rmSync(tempRoot, { recursive: true, force: true })
      tempRoot = null
    }
  })

  it('resolve o script local do Studio', () => {
    tempRoot = mkdtempSync(path.join(tmpdir(), 'subtitle-forge-'))
    writeFileSync(path.join(tempRoot, 'subtitle_forge.py'), '# external runner')

    const { scriptPath } = resolveHardsubScriptPath(tempRoot)

    expect(path.normalize(scriptPath ?? '')).toBe(
      path.normalize(path.resolve(process.cwd(), 'python', 'hardsub_service.py')),
    )
  })
})

describe('buildHardsubProcessArgs', () => {
  it('monta os args esperados pro modo zh-en', () => {
    const args = buildHardsubProcessArgs('hardsub_service.py', {
      videoPath: 'C:\\video.mp4',
      originalSrtPath: 'C:\\video.srt',
      sourceLanguage: 'pt',
      mode: 'zh-en',
      format: 'long',
      useCpu: false,
      videoType: 'gameplay de terror',
    })

    expect(args).toEqual([
      'hardsub_service.py',
      '--video',
      'C:\\video.mp4',
      '--original-srt',
      'C:\\video.srt',
      '--source-language',
      'pt',
      '--mode',
      'zh-en',
      '--format',
      'long',
      '--video-type',
      'gameplay de terror',
    ])
  })

  it('repassa o modo translate-zh (botao "Traduzir de novo") pro script', () => {
    const args = buildHardsubProcessArgs('hardsub_service.py', {
      videoPath: 'C:\video.mp4',
      originalSrtPath: 'C:\video.srt',
      sourceLanguage: 'pt',
      mode: 'translate-zh',
      format: 'shorts',
      useCpu: false,
    })

    expect(args[args.indexOf('--mode') + 1]).toBe('translate-zh')
  })

  it('omite --video-type quando nao ha contexto de video', () => {
    const args = buildHardsubProcessArgs('hardsub_service.py', {
      videoPath: 'C:\video.mp4',
      originalSrtPath: 'C:\video.srt',
      sourceLanguage: 'pt',
      mode: 'zh',
      format: 'long',
      useCpu: false,
    })

    expect(args).not.toContain('--video-type')
  })

  it('inclui --cpu quando useCpu true', () => {
    const args = buildHardsubProcessArgs('hardsub_service.py', {
      videoPath: 'C:\\video.mp4',
      originalSrtPath: 'C:\\video.srt',
      sourceLanguage: 'pt',
      mode: 'zh',
      format: 'shorts',
      useCpu: true,
    })

    expect(args).toContain('--cpu')
  })
})

describe('parseHardsubRunnerEvent', () => {
  it('reconhece eventos status/done/error', () => {
    const statusEvent = parseHardsubRunnerEvent(
      JSON.stringify({ event: 'status', status: 'processing', stage: 'burning', message: 'ok', progress: 40 }),
    )
    const doneEvent = parseHardsubRunnerEvent(
      JSON.stringify({ event: 'done', status: 'completed', stage: 'done', message: 'ok', outputPath: 'out.mp4' }),
    )

    expect(statusEvent?.event).toBe('status')
    expect(doneEvent?.event).toBe('done')
  })

  it('retorna null pra linha invalida', () => {
    expect(parseHardsubRunnerEvent('nao e json')).toBeNull()
  })
})
