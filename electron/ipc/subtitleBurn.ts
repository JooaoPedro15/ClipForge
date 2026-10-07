import crypto from 'node:crypto'
import path from 'node:path'

import { ipcMain, type WebContents } from 'electron'

import type { HardsubEvent, HardsubFormat, HardsubJobStatus, HardsubMode } from '../../src/types/subtitle.js'
import { gpuQueue, type JobResult } from '../python/gpuQueue.js'
import { resolveScriptPath } from '../python/pythonEnv.js'
import { runPython, type PythonRun } from '../python/pythonProcess.js'
import { decideOutcome, describeExitCode, parseRunnerLine } from '../python/runnerEvents.js'
import { getSubtitleTaskSnapshot, resolveSubtitleForgeRoot } from './subtitle.js'

// Tipos crus do runner e o registro do job sao so do processo principal; o contrato com a tela vem de src/types.
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

const RUNNER_EVENTS = ['status', 'done', 'error'] as const

interface HardsubJobRecord {
  id: string
  taskId: string
  sender: WebContents
  mode: HardsubMode
  format: HardsubFormat
  status: HardsubJobStatus
  outputPath: string | null
  lastMessage: string
  lastError: string | null
  process: PythonRun | null
  terminalEvent: RunnerDoneEvent | RunnerErrorEvent | null
}

const jobs = new Map<string, HardsubJobRecord>()

function emit(
  sender: WebContents,
  channel: 'subtitle:burn-progress' | 'subtitle:burn-done' | 'subtitle:burn-error',
  payload: HardsubEvent,
) {
  if (!sender.isDestroyed()) {
    sender.send(channel, payload)
  }
}

function toPayload(job: HardsubJobRecord, overrides: Partial<HardsubEvent>): HardsubEvent {
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
  return parseRunnerLine<HardsubRunnerEvent>(line, RUNNER_EVENTS)
}

function finishJob(job: HardsubJobRecord, code: number | null) {
  const outcome = decideOutcome({
    cancelRequested: false,
    terminalEvent: job.terminalEvent,
    code,
    lastError: job.lastError,
    lastMessage: job.lastMessage,
    defaultDoneMessage: 'Queima concluida.',
    describeExit: (exitCode) => describeExitCode(exitCode, 'processo de queima'),
    // Sem o evento 'done' nao ha caminho do video gerado: conta como erro.
    requireDoneEvent: true,
  })

  if (outcome.kind === 'done' && job.terminalEvent?.event === 'done') {
    job.status = 'completed'
    job.outputPath = job.terminalEvent.outputPath ?? job.outputPath
    emit(job.sender, 'subtitle:burn-done', toPayload(job, { status: 'completed', progress: 100, outputPath: job.outputPath }))
    return
  }

  job.status = 'error'
  const error = outcome.kind === 'error' ? outcome.error : outcome.message
  emit(job.sender, 'subtitle:burn-error', toPayload(job, { status: 'error', error }))
}

// Roda um job de queima da fila de GPU (espera transcricao/Pre-Editor que estiverem na frente).
async function runJob(job: HardsubJobRecord): Promise<JobResult> {
  const forgeRoot = resolveSubtitleForgeRoot()
  if (!forgeRoot) {
    job.status = 'error'
    emit(job.sender, 'subtitle:burn-error', toPayload(job, { status: 'error', error: 'Projeto subtitle-forge nao encontrado.' }))
    return 'done'
  }

  const { scriptPath } = resolveHardsubScriptPath(forgeRoot)
  if (!scriptPath) {
    job.status = 'error'
    emit(job.sender, 'subtitle:burn-error', toPayload(job, { status: 'error', error: 'Script hardsub_service.py nao encontrado.' }))
    return 'done'
  }

  const snapshot = getSubtitleTaskSnapshot(job.taskId)
  if (!snapshot || !snapshot.outputPath) {
    job.status = 'error'
    emit(job.sender, 'subtitle:burn-error', toPayload(job, { status: 'error', error: 'Tarefa de transcricao nao encontrada ou sem srt gerado.' }))
    return 'done'
  }

  job.status = 'preparing'
  emit(job.sender, 'subtitle:burn-progress', toPayload(job, { status: 'preparing', stage: 'starting', message: 'Preparando queima...', progress: 5 }))

  const run = runPython({
    root: forgeRoot,
    scriptArgs: buildHardsubProcessArgs(scriptPath, {
      videoPath: snapshot.filePath,
      originalSrtPath: snapshot.outputPath,
      sourceLanguage: snapshot.detectedLanguage ?? snapshot.language,
      mode: job.mode,
      format: job.format,
      useCpu: false,
      videoType: snapshot.videoType,
    }),
    logTag: 'hardsub-service',
    onStdoutLine: (line) => {
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
    },
    onStderrLine: (line) => {
      job.lastError = line
    },
  })
  job.process = run

  const { code, spawnError, lastStderrLine } = await run.done
  job.process = null
  if (spawnError && !lastStderrLine) {
    job.lastError = spawnError
  }

  finishJob(job, code)
  return 'done'
}

// Quando a queima espera atras de outro job da GPU, mostra a posicao na fila.
function emitQueued(job: HardsubJobRecord, position: number, isNext: boolean) {
  if (isNext) {
    return
  }

  job.lastMessage = `Na fila (${position})`
  emit(job.sender, 'subtitle:burn-progress', toPayload(job, { status: 'queued', stage: 'queued', message: job.lastMessage, progress: null }))
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
      process: null,
      terminalEvent: null,
    }

    jobs.set(jobId, job)
    emit(job.sender, 'subtitle:burn-progress', toPayload(job, { status: 'queued', stage: 'queued', message: job.lastMessage, progress: null }))
    gpuQueue.enqueue({
      id: jobId,
      onQueued: (position, isNext) => emitQueued(job, position, isNext),
      run: () => runJob(job),
    })

    return jobId
  })
}
