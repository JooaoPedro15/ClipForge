import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createFakeChild, type FakeChild } from '../testing/fakeChildProcess'
import { createLineSplitter, runPython, type SpawnFn } from './pythonProcess'

let root: string
let children: FakeChild[]

const fakeSpawn = ((command: string, args: string[], options: FakeChild['options']) => {
  const child = createFakeChild(command, args, options)
  children.push(child)
  return child
}) as unknown as SpawnFn

function onlyChild(): FakeChild {
  const child = children[0]
  if (!child) {
    throw new Error('processo nao iniciado')
  }
  return child
}

beforeEach(() => {
  root = mkdtempSync(path.join(tmpdir(), 'python-process-'))
  mkdirSync(path.join(root, '.venv', 'Scripts'), { recursive: true })
  writeFileSync(path.join(root, '.venv', 'Scripts', 'python.exe'), '')
  children = []
  vi.spyOn(console, 'error').mockImplementation(() => {})
})

afterEach(() => {
  vi.restoreAllMocks()
  rmSync(root, { recursive: true, force: true })
})

describe('createLineSplitter', () => {
  it('junta pedacos, ignora linhas vazias e entrega a sobra no flush', () => {
    const lines: string[] = []
    const splitter = createLineSplitter((line) => lines.push(line))

    splitter.push('primeira lin')
    splitter.push('ha\r\n\n  segunda  \nter')
    expect(lines).toEqual(['primeira linha', 'segunda'])

    splitter.flush()
    splitter.flush()
    expect(lines).toEqual(['primeira linha', 'segunda', 'ter'])
  })
})

describe('runPython', () => {
  it('sobe o Python do venv na raiz com o ambiente padrao e o extra', () => {
    const nvidiaBin = path.join(root, '.venv', 'Lib', 'site-packages', 'nvidia', 'cublas', 'bin')
    mkdirSync(nvidiaBin, { recursive: true })

    runPython(
      { root, scriptArgs: ['service.py', '--x'], extraEnv: { MINHA_VAR: 'sim' }, logTag: 'teste', onStdoutLine: () => {} },
      fakeSpawn,
    )

    const child = onlyChild()
    expect(child.command).toBe(path.join(root, '.venv', 'Scripts', 'python.exe'))
    expect(child.args).toEqual(['service.py', '--x'])
    expect(child.options.cwd).toBe(root)
    expect(child.options.env?.PYTHONUNBUFFERED).toBe('1')
    expect(child.options.env?.PYTHONIOENCODING).toBe('utf-8')
    expect(child.options.env?.MINHA_VAR).toBe('sim')
    expect(child.options.env?.PATH?.split(path.delimiter)[0]).toBe(nvidiaBin)
  })

  it('entrega linhas do stdout, guarda a ultima do stderr e resolve com o codigo', async () => {
    const stdout: string[] = []
    const stderr: string[] = []
    const run = runPython(
      { root, scriptArgs: ['s.py'], logTag: 'teste', onStdoutLine: (line) => stdout.push(line), onStderrLine: (line) => stderr.push(line) },
      fakeSpawn,
    )
    const child = onlyChild()

    child.emitStdout('{"a":1}\nparci')
    child.emitStderr('aviso\nTraceback final')
    child.close(2)

    await expect(run.done).resolves.toEqual({ code: 2, lastStderrLine: 'Traceback final', spawnError: null })
    expect(stdout).toEqual(['{"a":1}', 'parci'])
    expect(stderr).toEqual(['aviso', 'Traceback final'])
  })

  it('termina mesmo quando o spawn falha sem emitir close, e resolve uma vez so', async () => {
    const run = runPython({ root, scriptArgs: ['s.py'], logTag: 'teste', onStdoutLine: () => {} }, fakeSpawn)
    const child = onlyChild()

    child.emit('error', new Error('spawn python ENOENT'))
    const result = await run.done
    child.close(1)

    expect(result).toEqual({ code: null, lastStderrLine: null, spawnError: 'spawn python ENOENT' })
  })

  it('kill pede pro processo encerrar', () => {
    const run = runPython({ root, scriptArgs: ['s.py'], logTag: 'teste', onStdoutLine: () => {} }, fakeSpawn)

    run.kill()

    expect(onlyChild().killed).toBe(true)
  })
})
