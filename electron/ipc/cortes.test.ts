import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

import { describe, expect, test, vi } from 'vitest'

import { analysisPathFor, buildAnalyzeArgs, normalizeCortesOptions, readCortesAnalysis } from './cortes'

vi.mock('electron', () => ({ app: { getPath: () => 'C:\\userData' }, ipcMain: { handle: () => undefined } }))

describe('normalizeCortesOptions', () => {
  test('duracoes fora de ordem viram min <= alvo <= max', () => {
    expect(normalizeCortesOptions({ minSec: 200, targetSec: 90, maxSec: 100 })).toMatchObject({ minSec: 200, targetSec: 200, maxSec: 200 })
  })

  test('faixa invalida volta pro padrao e o trecho aceita virgula', () => {
    expect(normalizeCortesOptions({ filmTrack: 0, micTrack: Number.NaN, start: ' 2:24,44 ' })).toMatchObject({
      filmTrack: 1,
      micTrack: 2,
      start: '2:24.44',
      end: '',
      titlesWithAi: true,
    })
  })
})

describe('buildAnalyzeArgs', () => {
  test('bruto com espaco no nome, sem trecho e sem titulos com IA', () => {
    const options = normalizeCortesOptions({ titlesWithAi: false })
    expect(buildAnalyzeArgs('E:\\Bruto\\2026-07-28 23-40-19.mp4', options)).toEqual([
      'analyze',
      'E:\\Bruto\\2026-07-28 23-40-19.mp4',
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
      'none',
    ])
  })
})

describe('analysisPathFor', () => {
  test('troca a extensao do bruto como o Python (Path.with_suffix)', () => {
    expect(analysisPathFor('E:\\Bruto\\2026-07-28 23-40-19.mp4')).toBe(path.join('E:\\Bruto', '2026-07-28 23-40-19.cortes.json'))
  })
})

describe('readCortesAnalysis', () => {
  test('versao desconhecida e recusada com o nome do arquivo', () => {
    const folder = mkdtempSync(path.join(tmpdir(), 'cortes-read-'))
    const file = path.join(folder, 'react.cortes.json')
    writeFileSync(file, '{"version": 9}')
    try {
      expect(() => readCortesAnalysis(file)).toThrow('react.cortes.json')
    } finally {
      rmSync(folder, { recursive: true, force: true })
    }
  })
})
