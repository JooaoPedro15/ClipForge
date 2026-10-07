// Utilitarios dos testes de fluxo dos IPCs (raiz Python falsa, sender falso, projecao estavel).
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

import type { FakeChild } from './fakeChildProcess'

export type SentEvent = [channel: string, payload: Record<string, unknown>]

// Pasta temporaria com cara de projeto Python (tem .venv/Scripts/python.exe).
export function makePythonRoot(prefix: string): string {
  const root = mkdtempSync(path.join(tmpdir(), prefix))
  mkdirSync(path.join(root, '.venv', 'Scripts'), { recursive: true })
  writeFileSync(path.join(root, '.venv', 'Scripts', 'python.exe'), '')
  return root
}

// WebContents falso: so guarda o que o processo principal enviaria pra tela.
export function createSender() {
  const sent: SentEvent[] = []
  const sender = {
    isDestroyed: () => false,
    send: (channel: string, payload: Record<string, unknown>) => {
      sent.push([channel, payload])
    },
  }
  return { sent, sender }
}

// Deixa as continuacoes async (close -> proxima tarefa da fila) rodarem.
export function flush(): Promise<void> {
  return new Promise((resolve) => setImmediate(resolve))
}

export function jsonLine(event: Record<string, unknown>): string {
  return `${JSON.stringify(event)}\n`
}

const DEFAULT_KEYS = [
  'fileName',
  'sourceName',
  'mode',
  'status',
  'stage',
  'message',
  'progress',
  'queuePosition',
  'outputPath',
  'outputDir',
  'translatedOutputs',
  'translationErrors',
  'clipsCreated',
  'totalClips',
  'durationSec',
  'error',
]

// Tira o que muda a cada execucao (ids, horarios) e o que e vazio, pra caber num snapshot.
export function project(sent: SentEvent[], keys: string[] = DEFAULT_KEYS) {
  return sent.map(([channel, payload]) => {
    const picked: Record<string, unknown> = { ch: channel }
    for (const key of keys) {
      const value = payload[key]
      const isEmptyObject = typeof value === 'object' && value !== null && Object.keys(value).length === 0
      if (value !== undefined && value !== null && !isEmptyObject) {
        picked[key] = value
      }
    }
    return picked
  })
}

export function spawnSummary(child: FakeChild, root: string) {
  return {
    command: path.relative(root, child.command),
    script: path.basename(child.args[0] ?? ''),
    // A raiz temporaria muda a cada execucao: troca por um marcador fixo.
    args: child.args.slice(1).map((arg) => (arg === root ? '<root>' : arg)),
    cwdIsRoot: child.options.cwd === root,
    unbuffered: child.options.env?.PYTHONUNBUFFERED,
    ioEncoding: child.options.env?.PYTHONIOENCODING,
  }
}
