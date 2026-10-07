import { afterEach, describe, expect, it, vi } from 'vitest'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

vi.mock('electron', () => ({
  ipcMain: {
    handle: vi.fn(),
  },
}))

import { buildProcessArgs, parseRunnerEvent, resolveRunnerScriptPath } from './subtitle.js'

describe('buildProcessArgs', () => {
  it('inclui --translate-to quando translateTo tem idiomas', () => {
    const task = {
      filePath: 'C:\\video.mp4',
      options: {
        model: 'large-v3',
        language: 'pt',
        beamSize: 5,
        maxWidth: 42,
        maxWords: 0,
        uppercase: false,
        lowercase: false,
        noAccents: false,
        noPunctuation: false,
        useCpu: false,
        translateTo: ['en', 'zh'],
        videoType: 'gameplay de terror',
        outputPath: null,
      },
    } as Parameters<typeof buildProcessArgs>[1]

    const args = buildProcessArgs('script.py', task)

    expect(args).toContain('--translate-to')
    expect(args[args.indexOf('--translate-to') + 1]).toBe('en,zh')
    expect(args[args.indexOf('--video-type') + 1]).toBe('gameplay de terror')
  })

  it('omite --translate-to quando lista vazia', () => {
    const task = {
      filePath: 'C:\\video.mp4',
      options: {
        model: 'large-v3',
        language: 'pt',
        beamSize: 5,
        maxWidth: 42,
        maxWords: 0,
        uppercase: false,
        lowercase: false,
        noAccents: false,
        noPunctuation: false,
        useCpu: false,
        translateTo: [],
        videoType: '',
        outputPath: null,
      },
    } as Parameters<typeof buildProcessArgs>[1]

    const args = buildProcessArgs('script.py', task)

    expect(args).not.toContain('--translate-to')
    expect(args).not.toContain('--video-type')
  })
})

describe('buildProcessArgs com estilo aprendido', () => {
  const baseOptions = {
    model: 'large-v3',
    language: 'pt',
    beamSize: 5,
    maxWidth: 42,
    maxWords: 0,
    uppercase: false,
    lowercase: false,
    noAccents: false,
    noPunctuation: false,
    useCpu: false,
    translateTo: [],
    videoType: '',
    format: 'long',
    useStyle: true,
    outputPath: null,
  }

  it('passa --style-store quando o processo principal resolveu a pasta', () => {
    const task = { filePath: 'C:\\video.mp4', options: baseOptions, styleStore: 'C:\\userData\\subtitle-style' } as unknown as Parameters<
      typeof buildProcessArgs
    >[1]

    const args = buildProcessArgs('script.py', task)

    expect(args.slice(-2)).toEqual(['--style-store', 'C:\\userData\\subtitle-style'])
  })

  it('omite --style-store sem pasta', () => {
    const task = { filePath: 'C:\\video.mp4', options: baseOptions, styleStore: null } as unknown as Parameters<typeof buildProcessArgs>[1]

    expect(buildProcessArgs('script.py', task)).not.toContain('--style-store')
  })
})

describe('parseRunnerEvent', () => {
  it('reconhece eventos translation-done e translation-error', () => {
    const doneEvent = parseRunnerEvent(
      JSON.stringify({
        event: 'translation-done',
        status: 'completed',
        stage: 'translating',
        message: 'ok',
        targetLang: 'en',
        outputPath: 'C:\\video.en.srt',
      }),
    )
    const errorEvent = parseRunnerEvent(
      JSON.stringify({
        event: 'translation-error',
        status: 'error',
        stage: 'translating',
        message: 'falhou',
        targetLang: 'zh',
        error: 'sem internet',
      }),
    )

    expect(doneEvent?.event).toBe('translation-done')
    expect(errorEvent?.event).toBe('translation-error')
  })
})

describe('resolveRunnerScriptPath', () => {
  let tempRoot: string | null = null

  afterEach(() => {
    if (tempRoot) {
      rmSync(tempRoot, { recursive: true, force: true })
      tempRoot = null
    }
  })

  it('prefere o runner local do ClipForge quando tambem existe script externo', () => {
    tempRoot = mkdtempSync(path.join(tmpdir(), 'subtitle-forge-'))
    writeFileSync(path.join(tempRoot, 'subtitle_forge.py'), '# external runner')

    const { scriptPath } = resolveRunnerScriptPath(tempRoot)

    expect(path.normalize(scriptPath ?? '')).toBe(path.normalize(path.resolve(process.cwd(), 'python', 'subtitle_service.py')))
  })
})
