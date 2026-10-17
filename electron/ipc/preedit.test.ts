// Argumentos do preedit_service.py e resumo da biblioteca do Pre-editor que aprende.
import path from 'node:path'

import { describe, expect, it, vi } from 'vitest'

vi.mock('electron', () => ({ app: { getPath: () => 'C:\\AppData' }, ipcMain: { handle: vi.fn() } }))

import { buildEditArgs, buildTeachFinalsArgs, buildTeachProjectsArgs, preeditStorePath, summarizeLibrary } from './preedit.js'

describe('argumentos do Pre-editor que aprende', () => {
  it('edit com dois brutos e sem molde', () => {
    const args = buildEditArgs({ recordings: ['A.mkv', 'B.mkv'], minutes: 20, moldePath: '', zoomStyle: 'aproximando' }, 'S')

    expect(args).toEqual(['edit', '--recording', 'A.mkv', '--recording', 'B.mkv', '--minutes', '20', '--zoom-style', 'aproximando', '--store', 'S'])
  })

  it('edit com molde e zoom seco', () => {
    const args = buildEditArgs({ recordings: ['A.mkv'], minutes: 12.5, moldePath: 'M.xml', zoomStyle: 'seco' }, 'S')

    expect(args).toEqual(['edit', '--recording', 'A.mkv', '--minutes', '12.5', '--zoom-style', 'seco', '--molde', 'M.xml', '--store', 'S'])
  })

  it('ensino com projetos e com videos prontos', () => {
    expect(buildTeachProjectsArgs({ projects: ['a.prproj', 'b.prproj'] }, 'S')).toEqual([
      'teach-project',
      '--project',
      'a.prproj',
      '--project',
      'b.prproj',
      '--store',
      'S',
    ])
    expect(buildTeachFinalsArgs({ projectsDir: 'P', videosDir: 'V' }, 'S')).toEqual(['teach-final', '--projects-dir', 'P', '--videos', 'V', '--store', 'S'])
  })

  it('biblioteca fica na pasta de dados do app', () => {
    expect(preeditStorePath('C:\\AppData')).toBe(path.join('C:\\AppData', 'clip-forge', 'preedit-learning'))
  })

  it('resumo da biblioteca conta gravacoes com bruto e videos prontos por formato', () => {
    const report = {
      sources: [
        { kind: 'projeto', format: 'longo' },
        { kind: 'projeto', format: 'longo' },
        { kind: 'final', format: 'short' },
        { kind: 'final', format: 'short' },
        { kind: 'final', format: 'short' },
      ],
      models: { longo: {} },
    }

    expect(summarizeLibrary(report)).toEqual({ recordings: { longo: 2, short: 0 }, finals: { longo: 0, short: 3 }, editorReady: true })
    expect(summarizeLibrary(null)).toEqual({ recordings: { longo: 0, short: 0 }, finals: { longo: 0, short: 0 }, editorReady: false })
  })
})
