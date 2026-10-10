import crypto from 'node:crypto'
import { existsSync, readFileSync, rmSync } from 'node:fs'
import path from 'node:path'

import { ipcMain, type WebContents } from 'electron'

import type {
  CortesAnalysisSummary,
  CortesAnalyzeOptions,
  CortesClip,
  CortesDoneEvent,
  CortesDurations,
  CortesErrorEvent,
  CortesJobKind,
  CortesResegmentRequest,
  CortesTaskEventBase,
  CortesTaskStatus,
  CortesXmlRequest,
  CortesXmlResult,
} from '../../src/types/cortes.js'
import { gpuQueue, type JobResult } from '../python/gpuQueue.js'
import { resolveScriptPath } from '../python/pythonEnv.js'
import { runPython, type PythonRun } from '../python/pythonProcess.js'
import {
  decideOutcome,
  describeExitCode,
  looksLikeGpuFailure,
  parseRunnerLine,
  type RunnerEventBase,
} from '../python/runnerEvents.js'
import { resolveSubtitleForgeRoot } from './subtitle.js'

// Modelo do LLM local dos titulos (o juiz ficou fora da v1: so regras).
export const TITLE_MODEL = 'qwen2.5:7b-instruct'

// Eventos crus do cortes_service.py; o contrato com a tela vem de src/types/cortes.
interface RunnerStatusEvent extends RunnerEventBase {
  event: 'status'
  progress?: number | null
  // Pasta dos WAVs da leitura: o Electron apaga se o job for cancelado.
  tempDir?: string
}

interface RunnerWarningEvent extends RunnerEventBase {
  event: 'warning'
}

interface RunnerDoneEvent extends RunnerEventBase {
  event: 'done'
  outputPath?: string
}

interface RunnerErrorEvent extends RunnerEventBase {
  event: 'error'
  error?: string
}

type RunnerEvent = RunnerStatusEvent | RunnerWarningEvent | RunnerDoneEvent | RunnerErrorEvent

const RUNNER_EVENTS = ['status', 'warning', 'done', 'error'] as const

const FORGE_MISSING =
  'Projeto subtitle-forge nao encontrado (os cortes usam o Python e o Whisper dele). Configure em D:\\Projetos\\subtitle-forge ou use CLIPFORGE_SUBTITLE_FORGE_PATH.'
const SCRIPT_MISSING = 'Script cortes_service.py nao encontrado (pasta python/ do app).'

interface CortesTaskRecord {
  id: string
  kind: CortesJobKind
  sender: WebContents
  sourcePath: string
  sourceName: string
  analysisPath: string
  // Argumentos do cortes_service.py, sem o script e sem --cpu.
  args: string[]
  useCpu: boolean
  hasRetriedWithCpu: boolean
  status: CortesTaskStatus
  stage: string
  startedAt: number | null
  completedAt: number | null
  process: PythonRun | null
  cancelRequested: boolean
  lastMessage: string
  lastError: string | null
  terminalEvent: RunnerDoneEvent | RunnerErrorEvent | null
  warnings: string[]
  tempDir: string | null
}

// Jobs desta sessao (a ordem de execucao fica na fila unica de GPU).
const tasks = new Map<string, CortesTaskRecord>()

const defaultOptions: CortesAnalyzeOptions = {
  start: '',
  end: '',
  filmTrack: 1,
  micTrack: 2,
  minSec: 70,
  targetSec: 150,
  maxSec: 240,
  titlesWithAi: true,
}

function positive(value: unknown, fallback: number): number {
  const number = Number(value)
  return Number.isFinite(number) && number > 0 ? number : fallback
}

function track(value: unknown, fallback: number): number {
  const number = Math.trunc(Number(value))
  return Number.isFinite(number) && number >= 1 ? number : fallback
}

// Duracoes sempre em ordem (min <= alvo <= max) e com piso, pra programacao dinamica ter solucao.
export function normalizeDurations(input: Partial<CortesDurations>): CortesDurations {
  const minSec = Math.max(10, positive(input.minSec, defaultOptions.minSec))
  const maxSec = Math.max(minSec, positive(input.maxSec, defaultOptions.maxSec))
  const targetSec = Math.min(maxSec, Math.max(minSec, positive(input.targetSec, defaultOptions.targetSec)))
  return { minSec, targetSec, maxSec }
}

// Limpa as opcoes vindas da tela; o trecho aceita virgula como o resto do app.
export function normalizeCortesOptions(options: Partial<CortesAnalyzeOptions> | undefined): CortesAnalyzeOptions {
  const clock = (value: unknown) => String(value ?? '').trim().replace(',', '.')
  return {
    start: clock(options?.start),
    end: clock(options?.end),
    filmTrack: track(options?.filmTrack, defaultOptions.filmTrack),
    micTrack: track(options?.micTrack, defaultOptions.micTrack),
    ...normalizeDurations(options ?? {}),
    titlesWithAi: options?.titlesWithAi ?? defaultOptions.titlesWithAi,
  }
}

function durationArgs(durations: CortesDurations): string[] {
  return ['--min', String(durations.minSec), '--target', String(durations.targetSec), '--max', String(durations.maxSec)]
}

function titlesArg(titlesWithAi: boolean): string[] {
  return ['--titles', titlesWithAi ? TITLE_MODEL : 'none']
}

export function buildAnalyzeArgs(sourcePath: string, options: CortesAnalyzeOptions): string[] {
  const args = [
    'analyze',
    sourcePath,
    '--film-track',
    String(options.filmTrack),
    '--mic-track',
    String(options.micTrack),
    ...durationArgs(options),
    ...titlesArg(options.titlesWithAi),
  ]
  if (options.start) {
    args.push('--start', options.start)
  }
  if (options.end) {
    args.push('--end', options.end)
  }
  return args
}

export function buildResegmentArgs(request: CortesResegmentRequest): string[] {
  return ['resegment', request.analysisPath, ...durationArgs(normalizeDurations(request)), ...titlesArg(request.titlesWithAi)]
}

export function buildXmlArgs(request: CortesXmlRequest): string[] {
  return ['xml', '--template', request.templatePath, '--analysis', request.analysisPath, '--clips', request.clips.join(',')]
}

// Mesmo nome que o Python grava: Path(bruto).with_suffix(".cortes.json").
export function analysisPathFor(sourcePath: string): string {
  const parsed = path.parse(sourcePath)
  return path.join(parsed.dir, `${parsed.name}.cortes.json`)
}

interface RawAnalysis {
  version?: number
  source?: { path?: string; duration_sec?: number }
  options?: { start?: number; end?: number | null; min_sec?: number; target_sec?: number; max_sec?: number }
  clips?: Array<{ n: number; start: number; end: number; title?: string; hook?: number | null; score?: number | null }>
  warnings?: string[]
}

// Le o <bruto>.cortes.json do Python e devolve so o que a tela usa (a transcricao fica de fora).
export function readCortesAnalysis(analysisPath: string): CortesAnalysisSummary {
  const data = JSON.parse(readFileSync(analysisPath, 'utf8')) as RawAnalysis
  if (data.version !== 1 || !data.source || !data.options || !Array.isArray(data.clips)) {
    throw new Error(`${path.basename(analysisPath)} nao e uma analise de cortes que este app le.`)
  }

  const durationSec = data.source.duration_sec ?? 0
  return {
    analysisPath,
    sourcePath: data.source.path ?? '',
    durationSec,
    start: data.options.start ?? 0,
    end: data.options.end ?? durationSec,
    durations: {
      minSec: data.options.min_sec ?? defaultOptions.minSec,
      targetSec: data.options.target_sec ?? defaultOptions.targetSec,
      maxSec: data.options.max_sec ?? defaultOptions.maxSec,
    },
    clips: data.clips.map(
      (clip): CortesClip => ({
        n: clip.n,
        start: clip.start,
        end: clip.end,
        title: clip.title || `Clipe ${String(clip.n).padStart(2, '0')}`,
        hook: clip.hook ?? null,
        score: clip.score ?? null,
      }),
    ),
    warnings: Array.isArray(data.warnings) ? data.warnings : [],
  }
}

function resolveCortesScriptPath() {
  return resolveScriptPath([
    path.resolve(process.cwd(), 'python', 'cortes_service.py'),
    path.resolve(process.cwd(), '..', 'clip-forge', 'python', 'cortes_service.py'),
  ]).scriptPath
}

// Envia eventos para o renderer somente quando a janela ainda esta valida.
function send(sender: WebContents, channel: 'cortes:progress' | 'cortes:done' | 'cortes:error', payload: CortesTaskEventBase) {
  if (!sender.isDestroyed()) {
    sender.send(channel, payload)
  }
}

function toPayload(task: CortesTaskRecord, overrides: Partial<CortesTaskEventBase>): CortesTaskEventBase {
  return {
    taskId: task.id,
    kind: task.kind,
    sourcePath: task.sourcePath,
    sourceName: task.sourceName,
    status: task.status,
    stage: task.stage,
    message: task.lastMessage,
    progress: null,
    warnings: task.warnings,
    startedAt: task.startedAt ?? undefined,
    completedAt: task.completedAt ?? undefined,
    ...overrides,
  }
}

function emitProgress(task: CortesTaskRecord, overrides: Partial<CortesTaskEventBase>) {
  send(task.sender, 'cortes:progress', toPayload(task, overrides))
}

function emitDone(task: CortesTaskRecord, analysis: CortesAnalysisSummary, durationSec: number) {
  const completedAt = task.completedAt ?? Date.now()
  const payload: CortesDoneEvent = {
    ...toPayload(task, {}),
    status: 'completed',
    stage: 'done',
    progress: 100,
    completedAt,
    durationSec,
    analysis,
  }
  send(task.sender, 'cortes:done', payload)
}

function emitError(task: CortesTaskRecord, message: string, status: 'error' | 'cancelled') {
  const payload: CortesErrorEvent = { ...toPayload(task, { stage: status, message }), status, error: message }
  send(task.sender, 'cortes:error', payload)
}

// Avisa a tela da posicao do job na fila unica de GPU (chamado pela fila sempre que ela anda).
function emitQueued(task: CortesTaskRecord, position: number, isNext: boolean) {
  task.status = 'queued'
  task.stage = 'queued'
  task.lastMessage = isNext ? 'Aguardando inicializacao...' : `Na fila (${position})`
  emitProgress(task, { progress: null, queuePosition: position })
}

// So apaga pasta criada pelo modulo (cortes-*): o caminho chega pelo stdout do Python.
function removeTempDir(task: CortesTaskRecord) {
  const dir = task.tempDir
  task.tempDir = null
  if (!dir || !path.basename(dir).startsWith('cortes-')) {
    return
  }
  try {
    // O ffmpeg derrubado pode segurar o WAV por um instante: tenta de novo antes de desistir.
    rmSync(dir, { recursive: true, force: true, maxRetries: 3, retryDelay: 200 })
  } catch (error) {
    console.error('[cortes] nao consegui apagar a pasta temporaria', dir, error)
  }
}

function failTask(task: CortesTaskRecord, message: string) {
  task.status = 'error'
  task.completedAt = task.completedAt ?? Date.now()
  task.lastMessage = message
  removeTempDir(task)
  emitError(task, message, 'error')
}

function applyRunnerEvent(task: CortesTaskRecord, event: RunnerEvent) {
  if (event.event === 'warning') {
    task.warnings = [...task.warnings, event.message]
    emitProgress(task, {})
    return
  }

  task.lastMessage = event.message
  if (event.event === 'status') {
    if (event.tempDir) {
      task.tempDir = event.tempDir
    }
    task.status = 'processing'
    task.stage = event.stage
    emitProgress(task, { progress: event.progress ?? null })
    return
  }

  task.terminalEvent = event
}

// Consolida o desfecho quando o Python encerra: le a analise gravada ou explica o erro.
function finishTask(task: CortesTaskRecord, code: number | null) {
  task.completedAt = Date.now()
  const outcome = decideOutcome({
    cancelRequested: task.cancelRequested,
    terminalEvent: task.terminalEvent,
    code,
    lastError: task.lastError,
    lastMessage: task.lastMessage,
    defaultDoneMessage: 'Cortes prontos.',
    describeExit: (exitCode) => describeExitCode(exitCode, 'modulo de cortes'),
    requireDoneEvent: true,
  })

  if (outcome.kind === 'done') {
    let analysis: CortesAnalysisSummary
    try {
      analysis = readCortesAnalysis(task.analysisPath)
    } catch (error) {
      failTask(task, `A analise terminou, mas nao consegui ler ${path.basename(task.analysisPath)}: ${(error as Error).message}`)
      return
    }
    task.warnings = [...new Set([...analysis.warnings, ...task.warnings])]
    task.status = 'completed'
    task.stage = 'done'
    task.lastMessage = outcome.message
    const elapsed = task.startedAt ? Number(((task.completedAt - task.startedAt) / 1000).toFixed(1)) : 0
    emitDone(task, { ...analysis, warnings: task.warnings }, outcome.durationSec ?? elapsed)
    return
  }

  if (outcome.kind === 'cancelled') {
    task.status = 'cancelled'
    task.lastMessage = outcome.message
    removeTempDir(task)
    emitError(task, outcome.message, 'cancelled')
    return
  }

  failTask(task, outcome.error)
}

// So a leitura usa CUDA (Whisper/ffmpeg); refazer clipes nao tem o que repetir em CPU.
function shouldRetryOnCpu(task: CortesTaskRecord, code: number | null) {
  if (task.kind !== 'analyze' || task.useCpu || task.hasRetriedWithCpu || task.cancelRequested) {
    return false
  }
  return looksLikeGpuFailure(`${task.lastError ?? ''}\n${task.lastMessage}`, code)
}

// Roda um job da fila de GPU: sobe o Python, acompanha e decide entre retry em CPU e desfecho.
async function runTask(task: CortesTaskRecord): Promise<JobResult> {
  const root = resolveSubtitleForgeRoot()
  const scriptPath = resolveCortesScriptPath()
  if (!root || !scriptPath) {
    failTask(task, root ? SCRIPT_MISSING : FORGE_MISSING)
    return 'done'
  }

  task.status = 'preparing'
  task.stage = 'starting'
  task.startedAt = Date.now()
  task.terminalEvent = null
  task.lastError = null
  if (task.kind === 'resegment') {
    task.lastMessage = 'Refazendo os clipes...'
  } else {
    task.lastMessage = task.useCpu ? 'Iniciando a analise com Whisper em CPU...' : 'Iniciando a analise...'
  }
  emitProgress(task, { progress: 2 })

  const run = runPython({
    root,
    scriptArgs: [scriptPath, ...task.args, ...(task.useCpu ? ['--cpu'] : [])],
    logTag: 'cortes-service',
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
    // Em falhas tipicas de CUDA, o mesmo job volta ao topo da fila usando CPU.
    removeTempDir(task)
    task.useCpu = true
    task.hasRetriedWithCpu = true
    task.status = 'queued'
    task.stage = 'retrying-cpu'
    task.lastMessage = 'Falha no caminho CUDA. Tentando novamente em CPU...'
    emitProgress(task, { progress: null, queuePosition: 1 })
    return 'requeue-front'
  }

  finishTask(task, code)
  return 'done'
}

function createTask(id: string, kind: CortesJobKind, sender: WebContents, sourcePath: string, args: string[]): CortesTaskRecord {
  return {
    id,
    kind,
    sender,
    sourcePath,
    sourceName: path.basename(sourcePath),
    analysisPath: analysisPathFor(sourcePath),
    args,
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
    warnings: [],
    tempDir: null,
  }
}

function enqueue(task: CortesTaskRecord) {
  tasks.set(task.id, task)
  emitQueued(task, gpuQueue.size + 1, gpuQueue.size === 0 && !gpuQueue.busy)
  gpuQueue.enqueue({
    id: task.id,
    onQueued: (position, isNext) => emitQueued(task, position, isNext),
    run: () => runTask(task),
  })
}

function isActive(status: CortesTaskStatus) {
  return status === 'queued' || status === 'preparing' || status === 'processing'
}

// Gerar o XML so le o cortes.json e o molde: instantaneo, nao espera a fila de GPU.
export async function generateXml(request: CortesXmlRequest): Promise<CortesXmlResult> {
  if (!request.templatePath) {
    return { ok: false, error: 'Escolha o molde no Inspetor.' }
  }
  if (request.clips.length === 0) {
    return { ok: false, error: 'Marque pelo menos um clipe.' }
  }

  const root = resolveSubtitleForgeRoot()
  const scriptPath = resolveCortesScriptPath()
  if (!root || !scriptPath) {
    return { ok: false, error: root ? SCRIPT_MISSING : FORGE_MISSING }
  }

  let terminal: RunnerDoneEvent | RunnerErrorEvent | null = null
  const run = runPython({
    root,
    scriptArgs: [scriptPath, ...buildXmlArgs(request)],
    logTag: 'cortes-xml',
    onStdoutLine: (line) => {
      const event = parseRunnerLine<RunnerEvent>(line, RUNNER_EVENTS)
      if (event?.event === 'done' || event?.event === 'error') {
        terminal = event
      }
    },
  })

  const { code, lastStderrLine, spawnError } = await run.done
  const finished = terminal as RunnerDoneEvent | RunnerErrorEvent | null
  if (finished?.event === 'done' && finished.outputPath) {
    return { ok: true, outputPath: finished.outputPath }
  }
  if (finished?.event === 'error') {
    return { ok: false, error: finished.error ?? finished.message }
  }
  return { ok: false, error: lastStderrLine ?? spawnError ?? describeExitCode(code, 'gerador de XML') }
}

export function registerCortesHandlers() {
  // Analise do bruto inteiro (ou do trecho): leitura, transcricao, cortes e titulos.
  ipcMain.handle('cortes:analyze', (event, sourcePath: string, options?: Partial<CortesAnalyzeOptions>) => {
    const task = createTask(crypto.randomUUID(), 'analyze', event.sender, sourcePath, buildAnalyzeArgs(sourcePath, normalizeCortesOptions(options)))
    enqueue(task)
    return task.id
  })

  // Refazer clipes usa o id do item da tela: a lista nova substitui a antiga no mesmo lugar.
  ipcMain.handle('cortes:resegment', (event, taskId: string, request: CortesResegmentRequest) => {
    const current = tasks.get(taskId)
    if (current && isActive(current.status)) {
      return false
    }
    const task = createTask(taskId, 'resegment', event.sender, request.sourcePath, buildResegmentArgs(request))
    task.analysisPath = request.analysisPath
    enqueue(task)
    return true
  })

  // Cancela tanto jobs rodando quanto itens ainda na fila.
  ipcMain.handle('cortes:cancel', (_event, taskId: string) => {
    const task = tasks.get(taskId)
    if (!task) {
      return false
    }

    task.cancelRequested = true
    if (gpuQueue.has(taskId)) {
      task.status = 'cancelled'
      task.completedAt = Date.now()
      task.lastMessage = 'Tarefa cancelada antes de iniciar.'
      emitError(task, task.lastMessage, 'cancelled')
      gpuQueue.remove(taskId)
      return true
    }

    if (task.process) {
      task.process.kill()
      return true
    }

    return false
  })

  // Bruto ja analisado: devolve o resumo do <bruto>.cortes.json sem subir o Python.
  ipcMain.handle('cortes:load', (_event, sourcePath: string): CortesAnalysisSummary | null => {
    const analysisPath = analysisPathFor(sourcePath)
    if (!existsSync(analysisPath)) {
      return null
    }
    try {
      return readCortesAnalysis(analysisPath)
    } catch (error) {
      console.error('[cortes] analise ilegivel', analysisPath, error)
      return null
    }
  })

  ipcMain.handle('cortes:generate-xml', (_event, request: CortesXmlRequest) => generateXml(request))
}
