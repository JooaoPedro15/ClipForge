import { spawn, type ChildProcessByStdio } from 'node:child_process'
import crypto from 'node:crypto'
import path from 'node:path'
import type { Readable } from 'node:stream'

import { ipcMain, type WebContents } from 'electron'

import { resolveNvidiaBinPaths, resolvePythonCommand, resolveScriptPath } from '../python/pythonEnv.js'
import { getSubtitleTaskSnapshot, resolveSubtitleForgeRoot } from './subtitle.js'

// 'translate-zh' nao queima: so refaz a traducao (botao "Traduzir de novo").
export type HardsubMode = 'zh' | 'zh-en' | 'zh-original' | 'translate-zh'
export type HardsubFormat = 'shorts' | 'long'
type HardsubStatus = 'queued' | 'preparing' | 'processing' | 'completed' | 'error' | 'cancelled'

interface HardsubOptions {
  videoPath: string
  originalSrtPath: string
  sourceLanguage: string
  mode: HardsubMode
  format: HardsubFormat
  useCpu: boolean
  // Mesma linha de contexto da transcricao — o registro do chines depende dela.
  videoType?: string
}

interface HardsubEventPayload {
  taskId: string
  jobId: string
  mode: HardsubMode
  format: HardsubFormat
  status: HardsubStatus
  stage: string
  message: string
  progress: number | null
  outputPath?: string | null
  error?: string
}

interface RunnerStatusEvent {
  event: 'status'
  status: string
  stage: string
  message: string
  progress?: number | null
}

interface RunnerDoneEvent {
  event: 'done'
  status: string
  stage: string
  message: string
  progress?: number | null
  outputPath?: string
}

interface RunnerErrorEvent {
  event: 'error'
  status: string
  stage: string
  message: string
  error: string
}

type HardsubRunnerEvent = RunnerStatusEvent | RunnerDoneEvent | RunnerErrorEvent

interface HardsubJobRecord {
  id: string
  taskId: string
  sender: WebContents
  mode: HardsubMode
  format: HardsubFormat
  status: HardsubStatus
  outputPath: string | null
  lastMessage: string
  lastError: string | null
  child: ChildProcessByStdio<null, Readable, Readable> | null
  terminalEvent: RunnerDoneEvent | RunnerErrorEvent | null
}

const jobs = new Map<string, HardsubJobRecord>()
const queue: string[] = []
let activeJobId: string | null = null

function emit(
  sender: WebContents,
  channel: 'subtitle:burn-progress' | 'subtitle:burn-done' | 'subtitle:burn-error',
  payload: HardsubEventPayload,
) {
  if (!sender.isDestroyed()) {
    sender.send(channel, payload)
  }
}

function toPayload(job: HardsubJobRecord, overrides: Partial<HardsubEventPayload>): HardsubEventPayload {
  return {
    taskId: job.taskId,
    jobId: job.id,
    mode: job.mode,
    format: job.format,
    status: job.status,
    stage: 'idle',
    message: job.lastMessage,
    progress: null,
    outputPath: job.outputPath,
    ...overrides,
  }
}

export function resolveHardsubScriptPath(forgeRoot: string): { scriptPath: string | null; checked: string[] } {
  return resolveScriptPath([
    path.resolve(process.cwd(), 'python', 'hardsub_service.py'),
    path.resolve(process.cwd(), '..', 'clip-forge', 'python', 'hardsub_service.py'),
    path.join(forgeRoot, 'hardsub_service.py'),
  ])
}

export function buildHardsubProcessArgs(serviceScriptPath: string, options: HardsubOptions) {
  const args = [
    serviceScriptPath,
    '--video',
    options.videoPath,
    '--original-srt',
    options.originalSrtPath,
    '--source-language',
    options.sourceLanguage,
    '--mode',
    options.mode,
    '--format',
    options.format,
  ]

  if (options.useCpu) {
    args.push('--cpu')
  }

  if (options.videoType) {
    args.push('--video-type', options.videoType)
  }

  return args
}

export function parseHardsubRunnerEvent(line: string): HardsubRunnerEvent | null {
  try {
    const parsed = JSON.parse(line) as Partial<HardsubRunnerEvent>

    if (
      parsed &&
      (parsed.event === 'status' || parsed.event === 'done' || parsed.event === 'error') &&
      typeof parsed.status === 'string' &&
      typeof parsed.stage === 'string' &&
      typeof parsed.message === 'string'
    ) {
      return parsed as HardsubRunnerEvent
    }
  } catch {
    return null
  }

  return null
}

function flushBuffer(buffer: string, onLine: (line: string) => void) {
  const lines = buffer.split(/\r?\n/)
  const remainder = lines.pop() ?? ''

  for (const line of lines) {
    const trimmed = line.trim()
    if (trimmed) {
      onLine(trimmed)
    }
  }

  return remainder
}

function finishJob(job: HardsubJobRecord, code: number | null) {
  if (job.terminalEvent?.event === 'done') {
    job.status = 'completed'
    job.outputPath = job.terminalEvent.outputPath ?? job.outputPath
    emit(job.sender, 'subtitle:burn-done', toPayload(job, { status: 'completed', progress: 100, outputPath: job.outputPath }))
    return
  }

  if (job.terminalEvent?.event === 'error') {
    job.status = 'error'
    emit(job.sender, 'subtitle:burn-error', toPayload(job, { status: 'error', error: job.terminalEvent.error }))
    return
  }

  job.status = 'error'
  const message = job.lastError ?? `Processo finalizado com codigo ${code ?? 'desconhecido'}.`
  emit(job.sender, 'subtitle:burn-error', toPayload(job, { status: 'error', error: message }))
}

async function runNextJob() {
  if (activeJobId || queue.length === 0) {
    return
  }

  const nextJobId = queue.shift()
  const job = nextJobId ? jobs.get(nextJobId) : null
  if (!job) {
    await runNextJob()
    return
  }

  const forgeRoot = resolveSubtitleForgeRoot()
  if (!forgeRoot) {
    job.status = 'error'
    emit(job.sender, 'subtitle:burn-error', toPayload(job, { status: 'error', error: 'Projeto subtitle-forge nao encontrado.' }))
    await runNextJob()
    return
  }

  const { scriptPath } = resolveHardsubScriptPath(forgeRoot)
  if (!scriptPath) {
    job.status = 'error'
    emit(job.sender, 'subtitle:burn-error', toPayload(job, { status: 'error', error: 'Script hardsub_service.py nao encontrado.' }))
    await runNextJob()
    return
  }

  const snapshot = getSubtitleTaskSnapshot(job.taskId)
  if (!snapshot || !snapshot.outputPath) {
    job.status = 'error'
    emit(job.sender, 'subtitle:burn-error', toPayload(job, { status: 'error', error: 'Tarefa de transcricao nao encontrada ou sem srt gerado.' }))
    await runNextJob()
    return
  }

  activeJobId = job.id
  job.status = 'preparing'
  emit(job.sender, 'subtitle:burn-progress', toPayload(job, { status: 'preparing', stage: 'starting', message: 'Preparando queima...', progress: 5 }))

  const python = resolvePythonCommand(forgeRoot)
  const nvidiaBinPaths = resolveNvidiaBinPaths(forgeRoot)
  const args = [
    ...python.args,
    ...buildHardsubProcessArgs(scriptPath, {
      videoPath: snapshot.filePath,
      originalSrtPath: snapshot.outputPath,
      sourceLanguage: snapshot.detectedLanguage ?? snapshot.language,
      mode: job.mode,
      format: job.format,
      useCpu: false,
      videoType: snapshot.videoType,
    }),
  ]

  const child = spawn(python.command, args, {
    cwd: forgeRoot,
    env: {
      ...process.env,
      PATH: [...nvidiaBinPaths, process.env.PATH ?? ''].filter(Boolean).join(path.delimiter),
      PYTHONIOENCODING: 'utf-8',
      PYTHONUNBUFFERED: '1',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  })

  job.child = child
  let stdoutBuffer = ''
  let stderrBuffer = ''

  child.stdout.setEncoding('utf8')
  child.stderr.setEncoding('utf8')

  child.stdout.on('data', (chunk: string) => {
    stdoutBuffer += chunk
    stdoutBuffer = flushBuffer(stdoutBuffer, (line) => {
      const event = parseHardsubRunnerEvent(line)
      if (!event) {
        job.lastMessage = line
        return
      }

      job.lastMessage = event.message
      if (event.event === 'status') {
        emit(job.sender, 'subtitle:burn-progress', toPayload(job, { status: 'processing', stage: event.stage, message: event.message, progress: event.progress ?? null }))
      } else {
        job.terminalEvent = event
      }
    })
  })

  child.stderr.on('data', (chunk: string) => {
    stderrBuffer += chunk
    stderrBuffer = flushBuffer(stderrBuffer, (line) => {
      job.lastError = line
      console.error('[hardsub-service:stderr]', line)
    })
  })

  child.once('close', async (code) => {
    finishJob(job, code)
    job.child = null
    activeJobId = null
    await runNextJob()
  })
}

export function registerHardsubHandlers() {
  ipcMain.handle('subtitle:burn', async (event, taskId: string, mode: HardsubMode, format: HardsubFormat) => {
    const jobId = crypto.randomUUID()

    const job: HardsubJobRecord = {
      id: jobId,
      taskId,
      sender: event.sender,
      mode,
      format,
      status: 'queued',
      outputPath: null,
      lastMessage: 'Job de queima adicionado a fila.',
      lastError: null,
      child: null,
      terminalEvent: null,
    }

    jobs.set(jobId, job)
    queue.push(jobId)

    emit(job.sender, 'subtitle:burn-progress', toPayload(job, { status: 'queued', stage: 'queued', message: job.lastMessage, progress: null }))

    await runNextJob()

    return jobId
  })
}
