import crypto from 'node:crypto'
import path from 'node:path'

import { app, ipcMain, type WebContents } from 'electron'

import type {
  PreeditEditRequest,
  PreeditJobKind,
  PreeditJobRequest,
  PreeditLibrary,
  PreeditLibraryResult,
  PreeditTaskEvent,
  PreeditTaskStatus,
  PreeditTeachFinalsRequest,
  PreeditTeachProjectsRequest,
} from '../../src/types/preedit.js'
import { gpuQueue, type JobResult } from '../python/gpuQueue.js'
import { resolveScriptPath } from '../python/pythonEnv.js'
import { runPython, type PythonRun } from '../python/pythonProcess.js'
import { decideOutcome, describeExitCode, looksLikeGpuFailure, parseRunnerLine, type RunnerEventBase } from '../python/runnerEvents.js'
import { resolveSubtitleForgeRoot } from './subtitle.js'

// IA local das notas de interesse: o 14b nao cabe junto com o Whisper numa placa de 8 GB (mesmo dos Cortes).
const LOCAL_AI_MODEL = 'qwen2.5:7b-instruct'

// Eventos crus do preedit_service.py; o contrato com a tela vem de src/types/preedit.
interface RunnerStatusEvent extends RunnerEventBase {
  event: 'status'
  progress?: number | null
}

interface RunnerDoneEvent extends RunnerEventBase {
  event: 'done'
  report?: Record<string, unknown>
}

interface RunnerErrorEvent extends RunnerEventBase {
  event: 'error'
  error?: string
}

type RunnerEvent = RunnerStatusEvent | RunnerDoneEvent | RunnerErrorEvent

const RUNNER_EVENTS = ['status', 'done', 'error'] as const

const FORGE_MISSING =
  'Projeto subtitle-forge nao encontrado (a Pre-edicao usa o Python e o Whisper dele). Configure em D:\\Projetos\\subtitle-forge ou use CLIPFORGE_SUBTITLE_FORGE_PATH.'
const SCRIPT_MISSING = 'Script preedit_service.py nao encontrado (pasta python/ do app).'

interface PreeditTaskRecord {
  id: string
  job: PreeditJobRequest
  title: string
  sender: WebContents
  // Argumentos do preedit_service.py, sem o script e sem --cpu.
  args: string[]
  useCpu: boolean
  hasRetriedWithCpu: boolean
  status: PreeditTaskStatus
  stage: string
  startedAt: number | null
  completedAt: number | null
  process: PythonRun | null
  cancelRequested: boolean
  lastMessage: string
  lastError: string | null
  terminalEvent: RunnerDoneEvent | RunnerErrorEvent | null
}

const tasks = new Map<string, PreeditTaskRecord>()

export function preeditStorePath(appData: string): string {
  return path.join(appData, 'clip-forge', 'preedit-learning')
}

export function buildEditArgs(request: PreeditEditRequest, store: string): string[] {
  return [
    'edit',
    ...request.recordings.flatMap((recording) => ['--recording', recording]),
    '--minutes',
    String(request.minutes),
    '--zoom-style',
    request.zoomStyle,
    ...(request.moldePath ? ['--molde', request.moldePath] : []),
    '--store',
    store,
  ]
}

export function buildTeachProjectsArgs(request: PreeditTeachProjectsRequest, store: string): string[] {
  return ['teach-project', ...request.projects.flatMap((project) => ['--project', project]), '--store', store]
}

export function buildTeachFinalsArgs(request: PreeditTeachFinalsRequest, store: string): string[] {
  return ['teach-final', '--projects-dir', request.projectsDir, '--videos', request.videosDir, '--store', store]
}

function argsFor(job: PreeditJobRequest, store: string): string[] {
  if (job.kind === 'edit') {
    return buildEditArgs(job.request, store)
  }
  return job.kind === 'teach-projects' ? buildTeachProjectsArgs(job.request, store) : buildTeachFinalsArgs(job.request, store)
}

function titleFor(job: PreeditJobRequest): string {
  if (job.kind === 'edit') {
    const [first = '', ...rest] = job.request.recordings
    return rest.length ? `${path.basename(first)} +${rest.length}` : path.basename(first)
  }
  if (job.kind === 'teach-projects') {
    const count = job.request.projects.length
    return `Ensinar com ${count} projeto${count === 1 ? '' : 's'}`
  }
  return 'Ensinar com vídeos prontos'
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

// Do relatorio do Python (`report`): quantas fontes de cada tipo e formato, e se o editor do longo ja treinou.
export function summarizeLibrary(report: unknown): PreeditLibrary {
  const library: PreeditLibrary = { recordings: { longo: 0, short: 0 }, finals: { longo: 0, short: 0 }, editorReady: false }
  if (!isRecord(report)) {
    return library
  }
  for (const source of Array.isArray(report.sources) ? report.sources : []) {
    if (!isRecord(source) || (source.format !== 'longo' && source.format !== 'short')) {
      continue
    }
    const bucket = source.kind === 'final' ? library.finals : library.recordings
    bucket[source.format] += 1
  }
  library.editorReady = isRecord(report.models) && isRecord(report.models.longo)
  return library
}

function resolvePreeditScriptPath() {
  return resolveScriptPath([
    path.resolve(process.cwd(), 'python', 'preedit_service.py'),
    path.resolve(process.cwd(), '..', 'clip-forge', 'python', 'preedit_service.py'),
  ]).scriptPath
}

function send(sender: WebContents, channel: 'preedit:progress' | 'preedit:done' | 'preedit:error', payload: PreeditTaskEvent) {
  if (!sender.isDestroyed()) {
    sender.send(channel, payload)
  }
}

function toPayload(task: PreeditTaskRecord, overrides: Partial<PreeditTaskEvent>): PreeditTaskEvent {
  return {
    taskId: task.id,
    kind: task.job.kind as PreeditJobKind,
    title: task.title,
    status: task.status,
    stage: task.stage,
    message: task.lastMessage,
    progress: null,
    warnings: [],
    startedAt: task.startedAt ?? undefined,
    completedAt: task.completedAt ?? undefined,
    ...overrides,
  }
}

function emitQueued(task: PreeditTaskRecord, position: number, isNext: boolean) {
  task.status = 'queued'
  task.stage = 'queued'
  task.lastMessage = isNext ? 'Aguardando inicializacao...' : `Na fila (${position})`
  send(task.sender, 'preedit:progress', toPayload(task, { queuePosition: position }))
}

function emitError(task: PreeditTaskRecord, message: string, status: 'error' | 'cancelled') {
  task.status = status
  task.completedAt = task.completedAt ?? Date.now()
  task.lastMessage = message
  send(task.sender, 'preedit:error', { ...toPayload(task, { stage: status, message }), error: message })
}

function applyRunnerEvent(task: PreeditTaskRecord, event: RunnerEvent) {
  task.lastMessage = event.message
  if (event.event === 'status') {
    task.status = 'processing'
    task.stage = event.stage
    send(task.sender, 'preedit:progress', toPayload(task, { progress: event.progress ?? null }))
    return
  }
  task.terminalEvent = event
}

// Desfecho quando o Python encerra: o relatorio do evento 'done' vira o resultado do item.
function finishTask(task: PreeditTaskRecord, code: number | null) {
  task.completedAt = Date.now()
  const outcome = decideOutcome({
    cancelRequested: task.cancelRequested,
    terminalEvent: task.terminalEvent,
    code,
    lastError: task.lastError,
    lastMessage: task.lastMessage,
    defaultDoneMessage: 'Pronto.',
    describeExit: (exitCode) => describeExitCode(exitCode, 'Pre-editor'),
    requireDoneEvent: true,
  })
  if (outcome.kind === 'done') {
    const terminal = task.terminalEvent as RunnerDoneEvent
    const result = terminal.report ?? {}
    const warnings = Array.isArray(result.warnings) ? result.warnings.filter((item): item is string => typeof item === 'string') : []
    task.status = 'completed'
    task.stage = 'done'
    task.lastMessage = outcome.message
    send(task.sender, 'preedit:done', { ...toPayload(task, {}), progress: 100, warnings, result })
    return
  }
  if (outcome.kind === 'cancelled') {
    emitError(task, outcome.message, 'cancelled')
    return
  }
  emitError(task, outcome.error, 'error')
}

function shouldRetryOnCpu(task: PreeditTaskRecord, code: number | null) {
  if (task.useCpu || task.hasRetriedWithCpu || task.cancelRequested) {
    return false
  }
  return looksLikeGpuFailure(`${task.lastError ?? ''}\n${task.lastMessage}`, code)
}

// Roda um job da fila de GPU (Whisper e IA local): sobe o Python, acompanha e decide entre CPU e desfecho.
async function runTask(task: PreeditTaskRecord): Promise<JobResult> {
  const root = resolveSubtitleForgeRoot()
  const scriptPath = resolvePreeditScriptPath()
  if (!root || !scriptPath) {
    emitError(task, root ? SCRIPT_MISSING : FORGE_MISSING, 'error')
    return 'done'
  }

  task.status = 'preparing'
  task.stage = 'starting'
  task.startedAt = Date.now()
  task.terminalEvent = null
  task.lastError = null
  task.lastMessage = task.useCpu ? 'Iniciando com o Whisper em CPU...' : 'Iniciando...'
  send(task.sender, 'preedit:progress', toPayload(task, { progress: 2 }))

  const run = runPython({
    root,
    scriptArgs: [scriptPath, ...task.args, ...(task.useCpu ? ['--cpu'] : [])],
    extraEnv: { CLIPFORGE_OLLAMA_MODEL: LOCAL_AI_MODEL },
    logTag: 'preedit-service',
    onStdoutLine: (line) => {
      const event = parseRunnerLine<RunnerEvent>(line, RUNNER_EVENTS)
      if (event) {
        applyRunnerEvent(task, event)
      }
    },
    onStderrLine: (line) => {
      task.lastError = line
    },
  })
  task.process = run
  const { code, spawnError, lastStderrLine } = await run.done
  task.process = null
  if (spawnError && !lastStderrLine) {
    task.lastError = spawnError
  }

  if (shouldRetryOnCpu(task, code)) {
    task.useCpu = true
    task.hasRetriedWithCpu = true
    task.status = 'queued'
    task.stage = 'retrying-cpu'
    task.lastMessage = 'Falha no caminho CUDA. Tentando novamente em CPU...'
    send(task.sender, 'preedit:progress', toPayload(task, { queuePosition: 1 }))
    return 'requeue-front'
  }
  finishTask(task, code)
  return 'done'
}

function enqueue(sender: WebContents, job: PreeditJobRequest): string {
  const task: PreeditTaskRecord = {
    id: crypto.randomUUID(),
    job,
    title: titleFor(job),
    sender,
    args: argsFor(job, preeditStorePath(app.getPath('appData'))),
    useCpu: false,
    hasRetriedWithCpu: false,
    status: 'queued',
    stage: 'queued',
    startedAt: null,
    completedAt: null,
    process: null,
    cancelRequested: false,
    lastMessage: 'Tarefa adicionada a fila.',
    lastError: null,
    terminalEvent: null,
  }
  tasks.set(task.id, task)
  emitQueued(task, gpuQueue.size + 1, gpuQueue.size === 0 && !gpuQueue.busy)
  gpuQueue.enqueue({ id: task.id, onQueued: (position, isNext) => emitQueued(task, position, isNext), run: () => runTask(task) })
  return task.id
}

// Le a biblioteca (`report`): rapido, nao usa GPU, entao nao entra na fila.
export async function readLibrary(): Promise<PreeditLibraryResult> {
  const root = resolveSubtitleForgeRoot()
  const scriptPath = resolvePreeditScriptPath()
  if (!root || !scriptPath) {
    return { ok: false, error: root ? SCRIPT_MISSING : FORGE_MISSING }
  }
  let terminal: RunnerDoneEvent | RunnerErrorEvent | null = null
  const run = runPython({
    root,
    scriptArgs: [scriptPath, 'report', '--store', preeditStorePath(app.getPath('appData'))],
    logTag: 'preedit-report',
    onStdoutLine: (line) => {
      const event = parseRunnerLine<RunnerEvent>(line, RUNNER_EVENTS)
      if (event?.event === 'done' || event?.event === 'error') {
        terminal = event
      }
    },
  })
  const { code, lastStderrLine, spawnError } = await run.done
  const finished = terminal as RunnerDoneEvent | RunnerErrorEvent | null
  if (finished?.event === 'done') {
    return { ok: true, library: summarizeLibrary(finished.report) }
  }
  if (finished?.event === 'error') {
    return { ok: false, error: finished.error ?? finished.message }
  }
  return { ok: false, error: lastStderrLine ?? spawnError ?? describeExitCode(code, 'Pre-editor') }
}

export function registerPreeditHandlers() {
  ipcMain.handle('preedit:edit', (event, request: PreeditEditRequest) => enqueue(event.sender, { kind: 'edit', request }))
  ipcMain.handle('preedit:teach-projects', (event, request: PreeditTeachProjectsRequest) => enqueue(event.sender, { kind: 'teach-projects', request }))
  ipcMain.handle('preedit:teach-finals', (event, request: PreeditTeachFinalsRequest) => enqueue(event.sender, { kind: 'teach-finals', request }))

  // Cancela tanto o job rodando quanto o que ainda esta na fila.
  ipcMain.handle('preedit:cancel', (_event, taskId: string) => {
    const task = tasks.get(taskId)
    if (!task) {
      return false
    }
    task.cancelRequested = true
    if (gpuQueue.has(taskId)) {
      emitError(task, 'Tarefa cancelada antes de iniciar.', 'cancelled')
      gpuQueue.remove(taskId)
      return true
    }
    if (task.process) {
      task.process.kill()
      return true
    }
    return false
  })

  ipcMain.handle('preedit:library', () => readLibrary())
}
