import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'

import { ipcMain, type WebContents } from 'electron'

import {
  STYLE_MIN_VIDEOS,
  type StyleForgetReport,
  type StyleLearnRequest,
  type StyleLibrary,
  type StyleProfileName,
  type StyleProfileParams,
  type StyleProgressEvent,
  type StyleProjectLearnReport,
  type StyleProjectLearnRequest,
  type StyleProjectScan,
  type StyleReport,
  type StyleRunResult,
  type StyleVideoEntry,
} from '../../src/types/subtitleStyle.js'
import { gpuQueue } from '../python/gpuQueue.js'
import { resolveScriptPath } from '../python/pythonEnv.js'
import { runPython } from '../python/pythonProcess.js'
import { parseRunnerLine, type RunnerEventBase } from '../python/runnerEvents.js'
import { getStyleStoreDir } from '../styleStorePath.js'
import { resolveSubtitleForgeRoot } from './subtitle.js'

// Eventos crus do style_service.py (o relatorio vem no 'done').
interface StyleRunnerEvent extends RunnerEventBase {
  progress?: number | null
  report?: unknown
  error?: string
}

const RUNNER_EVENTS = ['status', 'done', 'error'] as const
const STYLE_PROFILES: StyleProfileName[] = ['vertical', 'horizontal']

export function resolveStyleScriptPath(forgeRoot: string) {
  return resolveScriptPath([
    path.resolve(process.cwd(), 'python', 'style_service.py'),
    path.resolve(process.cwd(), '..', 'clip-forge', 'python', 'style_service.py'),
    path.join(forgeRoot, 'style_service.py'),
  ])
}

// Argumentos do style_service.py (o caminho do script entra na frente em runStyleService).
export function buildStyleLearnArgs(request: StyleLearnRequest, storeDir: string) {
  const args = [
    'learn',
    '--original',
    request.originalPath,
    '--srt',
    request.srtPath,
    '--final',
    request.finalPath,
    '--store',
    storeDir,
    '--model',
    request.model,
    '--language',
    request.language,
  ]

  if (request.sequence) {
    args.push('--sequence', request.sequence)
  }

  if (request.useCpu) {
    args.push('--cpu')
  }

  return args
}

// Lista vira a opcao repetida (--originals A --originals B), como o argparse le com action="append".
function repeated(flag: string, values: string[] | undefined) {
  return (values ?? []).flatMap((value) => [flag, value])
}

export function buildStyleScanArgs(projectPath: string, originals?: string[]) {
  return ['scan-project', '--project', projectPath, ...repeated('--originals', originals)]
}

export function buildStyleLearnProjectArgs(request: StyleProjectLearnRequest, storeDir: string) {
  const args = ['learn-project', '--project', request.projectPath, '--store', storeDir, '--model', request.model, '--language', request.language]
  args.push(...repeated('--originals', request.originals), ...repeated('--finals', request.finals))
  if (request.only) {
    args.push('--only', request.only)
  }
  if (request.useCpu) {
    args.push('--cpu')
  }
  return args
}

export function buildStyleForgetArgs(videoId: string, storeDir: string) {
  return ['forget', '--id', videoId, '--store', storeDir]
}

function readJsonFile<T>(filePath: string): T | null {
  if (!existsSync(filePath)) {
    return null
  }

  try {
    return JSON.parse(readFileSync(filePath, 'utf8')) as T
  } catch {
    return null
  }
}

// Le a biblioteca direto dos JSONs gravados pelo Python (rapido: nao sobe processo).
export function readStyleLibrary(storeDir: string): StyleLibrary {
  const library = readJsonFile<{ videos?: StyleVideoEntry[] }>(path.join(storeDir, 'library.json'))
  const profiles: StyleLibrary['profiles'] = {}

  for (const name of STYLE_PROFILES) {
    const profileDir = path.join(storeDir, 'profiles', name)
    const params = readJsonFile<StyleProfileParams>(path.join(profileDir, 'params.json'))
    if (!params) {
      continue
    }

    const treePath = path.join(profileDir, 'tree.txt')
    profiles[name] = { params, tree: existsSync(treePath) ? readFileSync(treePath, 'utf8') : '' }
  }

  return { videos: library?.videos ?? [], profiles, minVideos: STYLE_MIN_VIDEOS }
}

function sendProgress(sender: WebContents, event: StyleProgressEvent) {
  if (!sender.isDestroyed()) {
    sender.send('subtitleStyle:progress', event)
  }
}

// Roda o style_service.py e devolve o relatorio do 'done' ou a mensagem do erro.
async function runStyleService<T>(scriptArgs: string[], sender: WebContents | null): Promise<StyleRunResult<T>> {
  const forgeRoot = resolveSubtitleForgeRoot()
  if (!forgeRoot) {
    return { ok: false, error: 'Projeto subtitle-forge nao encontrado. Configure em D:\\Projetos\\subtitle-forge ou use CLIPFORGE_SUBTITLE_FORGE_PATH.' }
  }

  const { scriptPath, checked } = resolveStyleScriptPath(forgeRoot)
  if (!scriptPath) {
    return { ok: false, error: `Script style_service.py nao encontrado. Caminhos verificados:\n${checked.join('\n')}` }
  }

  let terminal: StyleRunnerEvent | null = null
  const run = runPython({
    root: forgeRoot,
    scriptArgs: [scriptPath, ...scriptArgs],
    logTag: 'style-service',
    onStdoutLine: (line) => {
      const event = parseRunnerLine<StyleRunnerEvent>(line, RUNNER_EVENTS)
      if (!event) {
        return
      }

      if (event.event === 'status') {
        if (sender) {
          sendProgress(sender, { stage: event.stage, message: event.message, progress: event.progress ?? null })
        }
        return
      }

      terminal = event
    },
  })

  const { code, lastStderrLine, spawnError } = await run.done
  const finished = terminal as StyleRunnerEvent | null
  if (finished?.event === 'done') {
    return { ok: true, report: finished.report as T }
  }

  if (finished?.event === 'error') {
    return { ok: false, error: finished.error ?? finished.message }
  }

  return { ok: false, error: lastStderrLine ?? spawnError ?? `Processo finalizado com codigo ${code ?? 'desconhecido'}.` }
}

function enqueueStyleJob<T>(scriptArgs: string[], sender: WebContents): Promise<StyleRunResult<T>> {
  return new Promise((resolve) => {
    gpuQueue.enqueue({
      id: `style-${Date.now()}`,
      onQueued: (position, isNext) =>
        sendProgress(sender, { stage: 'queued', message: isNext ? 'Aguardando inicializacao...' : `Na fila (${position})`, progress: null }),
      run: async () => {
        resolve(await runStyleService<T>(scriptArgs, sender))
        return 'done'
      },
    })
  })
}

export function registerSubtitleStyleHandlers() {
  ipcMain.handle('subtitleStyle:list', async (): Promise<StyleLibrary> => readStyleLibrary(getStyleStoreDir()))

  // Ensinar (um ou todos) roda o Whisper: entra na fila unica de GPU e espera transcricao/queima/Pre-Editor da frente.
  ipcMain.handle('subtitleStyle:learn', (event, request: StyleLearnRequest): Promise<StyleRunResult<StyleReport>> =>
    enqueueStyleJob<StyleReport>(buildStyleLearnArgs(request, getStyleStoreDir()), event.sender),
  )
  ipcMain.handle(
    'subtitleStyle:learnProject',
    (event, request: StyleProjectLearnRequest): Promise<StyleRunResult<StyleProjectLearnReport>> =>
      enqueueStyleJob<StyleProjectLearnReport>(buildStyleLearnProjectArgs(request, getStyleStoreDir()), event.sender),
  )

  // Ler o projeto do Premiere so abre o XML (sem Whisper): fora da fila de GPU.
  ipcMain.handle(
    'subtitleStyle:scanProject',
    (_event, projectPath: string, originals?: string[]): Promise<StyleRunResult<StyleProjectScan>> =>
      runStyleService<StyleProjectScan>(buildStyleScanArgs(projectPath, originals), null),
  )

  // Esquecer so mexe nos arquivos da biblioteca e retreina a arvore: rapido, nao precisa da fila de GPU.
  ipcMain.handle('subtitleStyle:forget', (_event, videoId: string): Promise<StyleRunResult<StyleForgetReport>> =>
    runStyleService<StyleForgetReport>(buildStyleForgetArgs(videoId, getStyleStoreDir()), null),
  )
}
