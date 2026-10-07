import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { resolveNvidiaBinPaths, resolveProjectRoot, resolvePythonCommand, resolveScriptPath } from './pythonEnv'

let base: string

function touch(...parts: string[]) {
  const file = path.join(base, ...parts)
  mkdirSync(path.dirname(file), { recursive: true })
  writeFileSync(file, '')
  return file
}

beforeEach(() => {
  base = mkdtempSync(path.join(tmpdir(), 'python-env-'))
})

afterEach(() => {
  rmSync(base, { recursive: true, force: true })
})

describe('resolveProjectRoot', () => {
  it('escolhe a primeira candidata com venv ou arquivo marcador, ignorando vazias', () => {
    touch('sem-nada', 'leia-me.txt')
    touch('com-marcador', 'subtitle_forge.py')
    touch('com-venv', 'venv', 'Scripts', 'python.exe')

    const candidates = [undefined, '', path.join(base, 'sem-nada'), path.join(base, 'com-marcador'), path.join(base, 'com-venv')]

    expect(resolveProjectRoot(candidates, 'subtitle_forge.py')).toBe(path.join(base, 'com-marcador'))
    expect(resolveProjectRoot([path.join(base, 'com-venv')], 'outro.py')).toBe(path.join(base, 'com-venv'))
    expect(resolveProjectRoot([path.join(base, 'sem-nada')], 'subtitle_forge.py')).toBeNull()
  })
})

describe('resolvePythonCommand', () => {
  it('prefere .venv, depois venv, e cai no python do sistema', () => {
    const venv = touch('venv', 'Scripts', 'python.exe')
    expect(resolvePythonCommand(base)).toEqual({ command: venv, args: [] })

    const dotVenv = touch('.venv', 'Scripts', 'python.exe')
    expect(resolvePythonCommand(base)).toEqual({ command: dotVenv, args: [] })

    expect(resolvePythonCommand(path.join(base, 'vazio'))).toEqual({ command: 'python', args: [] })
  })
})

describe('resolveNvidiaBinPaths', () => {
  it('lista so as pastas bin das libs CUDA que existem, .venv antes de venv', () => {
    mkdirSync(path.join(base, 'venv', 'Lib', 'site-packages', 'nvidia', 'cudnn', 'bin'), { recursive: true })
    mkdirSync(path.join(base, '.venv', 'Lib', 'site-packages', 'nvidia', 'cublas', 'bin'), { recursive: true })

    expect(resolveNvidiaBinPaths(base)).toEqual([
      path.join(base, '.venv', 'Lib', 'site-packages', 'nvidia', 'cublas', 'bin'),
      path.join(base, 'venv', 'Lib', 'site-packages', 'nvidia', 'cudnn', 'bin'),
    ])
  })
})

describe('resolveScriptPath', () => {
  it('devolve o primeiro script existente e a lista do que foi verificado', () => {
    const second = touch('b', 'service.py')
    const checked = [path.join(base, 'a', 'service.py'), second]

    expect(resolveScriptPath(checked)).toEqual({ scriptPath: second, checked })
    expect(resolveScriptPath([path.join(base, 'nada.py')]).scriptPath).toBeNull()
  })
})
