// Sobe um servico Python e entrega o stdout/stderr linha a linha (eventos JSON ou log livre).
import { spawn } from 'node:child_process'
import path from 'node:path'

import { resolveNvidiaBinPaths, resolvePythonCommand } from './pythonEnv.js'

export type SpawnFn = typeof spawn

export interface RunPythonOptions {
  // Pasta do projeto Python: vira o cwd e e onde se procura o venv e as DLLs CUDA.
  root: string
  // Script seguido dos argumentos dele.
  scriptArgs: string[]
  extraEnv?: Record<string, string>
  // Prefixo do console.error do stderr (ex.: 'subtitle-service').
  logTag: string
  onStdoutLine: (line: string) => void
  onStderrLine?: (line: string) => void
}

export interface RunPythonResult {
  code: number | null
  lastStderrLine: string | null
  spawnError: string | null
}

export interface PythonRun {
  kill: () => void
  done: Promise<RunPythonResult>
}

// Junta os pedacos do fluxo e so entrega linhas completas; flush() solta a ultima sem quebra de linha.
export function createLineSplitter(onLine: (line: string) => void) {
  let buffer = ''

  const emitLine = (line: string) => {
    const trimmed = line.trim()
    if (trimmed) {
      onLine(trimmed)
    }
  }

  return {
    push(chunk: string) {
      buffer += chunk
      const lines = buffer.split(/\r?\n/)
      buffer = lines.pop() ?? ''
      lines.forEach(emitLine)
    },
    flush() {
      const rest = buffer
      buffer = ''
      emitLine(rest)
    },
  }
}

export type KillTreeFn = (pid: number) => void

// No Windows, child.kill() encerra so o python.exe: o ffmpeg que ele abriu (queima,
// Pre-Editor) fica orfao, rodando ate o fim. taskkill /T derruba a arvore inteira.
function killWindowsTree(pid: number) {
  const killer = spawn('taskkill', ['/pid', String(pid), '/T', '/F'], { stdio: 'ignore', windowsHide: true })
  // Sem taskkill: encerra ao menos o python (pode ja ter saido, dai o try).
  killer.once('error', () => {
    try {
      process.kill(pid)
    } catch {
      // processo ja terminou
    }
  })
}

const defaultKillTree: KillTreeFn | null = process.platform === 'win32' ? killWindowsTree : null

export function runPython(
  options: RunPythonOptions,
  spawnFn: SpawnFn = spawn,
  killTree: KillTreeFn | null = defaultKillTree,
): PythonRun {
  const python = resolvePythonCommand(options.root)
  const nvidiaBinPaths = resolveNvidiaBinPaths(options.root)
  // stdout/stderr em pipe pra alimentar a UI em tempo real.
  const child = spawnFn(python.command, [...python.args, ...options.scriptArgs], {
    cwd: options.root,
    env: {
      ...process.env,
      ...options.extraEnv,
      PATH: [...nvidiaBinPaths, process.env.PATH ?? ''].filter(Boolean).join(path.delimiter),
      PYTHONIOENCODING: 'utf-8',
      PYTHONUNBUFFERED: '1',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  })

  let lastStderrLine: string | null = null
  let spawnError: string | null = null

  const stdout = createLineSplitter(options.onStdoutLine)
  const stderr = createLineSplitter((line) => {
    lastStderrLine = line
    console.error(`[${options.logTag}:stderr]`, line)
    options.onStderrLine?.(line)
  })

  child.stdout.setEncoding('utf8')
  child.stderr.setEncoding('utf8')
  child.stdout.on('data', (chunk: string) => stdout.push(chunk))
  child.stderr.on('data', (chunk: string) => stderr.push(chunk))

  const done = new Promise<RunPythonResult>((resolve) => {
    let settled = false
    const finish = (code: number | null) => {
      if (settled) {
        return
      }
      settled = true
      stdout.flush()
      stderr.flush()
      resolve({ code, lastStderrLine, spawnError })
    }

    child.once('close', (code: number | null) => finish(code))
    // Spawn que falha (ex.: python inexistente) pode nao emitir 'close': termina mesmo assim.
    child.once('error', (error: Error) => {
      spawnError = error.message
      setImmediate(() => finish(null))
    })
  })

  return {
    kill: () => {
      if (killTree && child.pid !== undefined) {
        killTree(child.pid)
        return
      }
      child.kill()
    },
    done,
  }
}
