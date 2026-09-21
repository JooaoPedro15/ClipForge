import { create } from 'zustand'

import type {
  ClipFeedbackLabel,
  ClipSplitterDoneEvent,
  ClipSplitterErrorEvent,
  ClipSplitterProgressEvent,
  ClipSplitterOptions,
  ClipSplitterTask,
} from '@/types/clipSplitter'
import type {
  HardsubEvent,
  SubtitleDoneEvent,
  SubtitleErrorEvent,
  SubtitleProgressEvent,
  SubtitleTask,
  SubtitleTaskOptions,
  ToolId,
} from '@/types/subtitle'

// Configuracao inicial do SubtitleForge exibida quando o app abre.
const defaultSubtitleSettings: SubtitleTaskOptions = {
  model: 'large-v3',
  language: 'pt',
  beamSize: 5,
  maxWidth: 42,
  maxWords: 0,
  uppercase: false,
  lowercase: false,
  noAccents: false,
  noPunctuation: false,
  useCpu: false,
  translateTo: [],
  videoType: '',
  format: 'long',
  outputPath: null,
}

// Configuracao inicial do Pre-Editor com o modo padrao da ferramenta.
const defaultClipSplitterSettings: ClipSplitterOptions = {
  useAi: false,
  mode: 'silence',
  preEditMode: 'balanced',
  writeDebugJson: false,
  analysisAudioTrack: '1',
  targetDurationSec: 35,
  minClipDurationSec: 20,
  maxClipDurationSec: 50,
  silenceThresholdDb: -35,
  silenceMinDurationSec: 0.45,
  outputDir: null,
}

// Garante que minimo, maximo e alvo de duracao nunca fiquem em combinacoes invalidas.
function normalizeClipSplitterSettings(settings: ClipSplitterOptions): ClipSplitterOptions {
  const minClipDurationSec = Math.max(5, Number(settings.minClipDurationSec))
  const maxClipDurationSec = Math.max(minClipDurationSec + 1, Number(settings.maxClipDurationSec))
  const targetDurationSec = Math.min(
    maxClipDurationSec,
    Math.max(minClipDurationSec, Number(settings.targetDurationSec)),
  )

  return {
    ...settings,
    targetDurationSec,
    minClipDurationSec,
    maxClipDurationSec,
    silenceMinDurationSec: Math.max(0.1, Number(settings.silenceMinDurationSec)),
  }
}

// Contrato central da store global usada por toda a interface.
interface AppState {
  activeTool: ToolId
  subtitleSettings: SubtitleTaskOptions
  subtitleTasks: SubtitleTask[]
  clipSplitterSettings: ClipSplitterOptions
  clipSplitterTasks: ClipSplitterTask[]
  clipSplitterSourcePath: string | null
  setActiveTool: (tool: ToolId) => void
  patchSubtitleSettings: (patch: Partial<SubtitleTaskOptions>) => void
  setSubtitleOutputPath: (outputPath: string | null) => void
  upsertSubtitleProgress: (event: SubtitleProgressEvent) => void
  completeSubtitleTask: (event: SubtitleDoneEvent) => void
  failSubtitleTask: (event: SubtitleErrorEvent) => void
  upsertHardsubJob: (event: HardsubEvent) => void
  patchClipSplitterSettings: (patch: Partial<ClipSplitterOptions>) => void
  setClipSplitterOutputDir: (outputDir: string | null) => void
  setClipSplitterSourcePath: (sourcePath: string | null) => void
  upsertClipSplitterProgress: (event: ClipSplitterProgressEvent) => void
  completeClipSplitterTask: (event: ClipSplitterDoneEvent) => void
  failClipSplitterTask: (event: ClipSplitterErrorEvent) => void
  setClipFeedbackForTask: (taskId: string, clipId: string, label: ClipFeedbackLabel | null) => void
}

// Insere ou atualiza uma tarefa de legenda conforme os eventos vindos do backend.
function upsertSubtitleTask(
  tasks: SubtitleTask[],
  event: SubtitleProgressEvent | SubtitleDoneEvent | SubtitleErrorEvent,
): SubtitleTask[] {
  const currentIndex = tasks.findIndex((task) => task.id === event.taskId)
  const currentTask = currentIndex >= 0 ? tasks[currentIndex] : null

  const nextTask: SubtitleTask = {
    id: event.taskId,
    filePath: event.filePath,
    fileName: event.fileName,
    outputPath: event.outputPath ?? currentTask?.outputPath ?? null,
    model: event.model,
    language: event.language,
    detectedLanguage: event.detectedLanguage ?? currentTask?.detectedLanguage ?? null,
    device: event.device,
    status: event.status,
    stage: event.stage,
    message: event.message,
    progress: event.progress ?? currentTask?.progress ?? null,
    queuePosition: event.queuePosition ?? currentTask?.queuePosition ?? null,
    processedSegments: event.processedSegments ?? currentTask?.processedSegments ?? 0,
    totalSegments: event.totalSegments ?? currentTask?.totalSegments ?? null,
    createdAt: currentTask?.createdAt ?? Date.now(),
    startedAt: event.startedAt ?? currentTask?.startedAt ?? null,
    completedAt: event.completedAt ?? currentTask?.completedAt ?? null,
    durationSec: event.durationSec ?? currentTask?.durationSec ?? null,
    error: 'error' in event ? event.error : currentTask?.error ?? null,
    translatedOutputs: { ...currentTask?.translatedOutputs, ...event.translatedOutputs },
    translationErrors: { ...currentTask?.translationErrors, ...event.translationErrors },
    hardsubJobs: currentTask?.hardsubJobs ?? {},
  }

  if (currentIndex === -1) {
    return [nextTask, ...tasks]
  }

  return tasks.map((task) => (task.id === event.taskId ? nextTask : task))
}

// Insere ou atualiza uma tarefa de corte conforme o progresso do runner.
function upsertClipSplitterTask(
  tasks: ClipSplitterTask[],
  event: ClipSplitterProgressEvent | ClipSplitterDoneEvent | ClipSplitterErrorEvent,
): ClipSplitterTask[] {
  const currentIndex = tasks.findIndex((task) => task.id === event.taskId)
  const currentTask = currentIndex >= 0 ? tasks[currentIndex] : null

  const nextTask: ClipSplitterTask = {
    id: event.taskId,
    sourcePath: event.sourcePath,
    sourceName: event.sourceName,
    mode: event.mode,
    aiRequested: event.aiRequested ?? currentTask?.aiRequested ?? false,
    aiUsed: event.aiUsed ?? currentTask?.aiUsed ?? null,
    fallbackReason: event.fallbackReason ?? currentTask?.fallbackReason ?? null,
    status: event.status,
    stage: event.stage,
    message: event.message,
    progress: event.progress ?? currentTask?.progress ?? null,
    queuePosition: event.queuePosition ?? currentTask?.queuePosition ?? null,
    outputDir: event.outputDir ?? currentTask?.outputDir ?? null,
    debugPath: event.debugPath ?? currentTask?.debugPath ?? null,
    clipsCreated: event.clipsCreated ?? currentTask?.clipsCreated ?? 0,
    totalClips: event.totalClips ?? currentTask?.totalClips ?? null,
    sourceDurationSec: event.sourceDurationSec ?? currentTask?.sourceDurationSec ?? null,
    createdAt: currentTask?.createdAt ?? Date.now(),
    startedAt: event.startedAt ?? currentTask?.startedAt ?? null,
    completedAt: event.completedAt ?? currentTask?.completedAt ?? null,
    durationSec: event.durationSec ?? currentTask?.durationSec ?? null,
    error: 'error' in event ? event.error : currentTask?.error ?? null,
    clips: event.clips ?? currentTask?.clips ?? [],
  }

  if (currentIndex === -1) {
    return [nextTask, ...tasks]
  }

  return tasks.map((task) => (task.id === event.taskId ? nextTask : task))
}

// Store Zustand com estado compartilhado, configuracoes e mutacoes do app inteiro.
export const useAppStore = create<AppState>((set) => ({
  activeTool: 'subtitle-forge',
  subtitleSettings: defaultSubtitleSettings,
  subtitleTasks: [],
  clipSplitterSettings: normalizeClipSplitterSettings(defaultClipSplitterSettings),
  clipSplitterTasks: [],
  clipSplitterSourcePath: null,
  setActiveTool: (tool) => set({ activeTool: tool }),
  // Faz merge parcial das preferencias da transcricao sem perder o resto do objeto.
  patchSubtitleSettings: (patch) =>
    set((state) => ({
      subtitleSettings: {
        ...state.subtitleSettings,
        ...patch,
      },
    })),
  setSubtitleOutputPath: (outputPath) =>
    set((state) => ({
      subtitleSettings: {
        ...state.subtitleSettings,
        outputPath,
      },
    })),
  upsertSubtitleProgress: (event) =>
    set((state) => ({
      subtitleTasks: upsertSubtitleTask(state.subtitleTasks, event),
    })),
  completeSubtitleTask: (event) =>
    set((state) => ({
      subtitleTasks: upsertSubtitleTask(state.subtitleTasks, event),
    })),
  failSubtitleTask: (event) =>
    set((state) => ({
      subtitleTasks: upsertSubtitleTask(state.subtitleTasks, event),
    })),
  upsertHardsubJob: (event) =>
    set((state) => ({
      subtitleTasks: state.subtitleTasks.map((task) => {
        if (task.id !== event.taskId) {
          return task
        }

        return {
          ...task,
          hardsubJobs: {
            ...task.hardsubJobs,
            [event.mode]: {
              status: event.status,
              stage: event.stage,
              message: event.message,
              progress: event.progress,
              outputPath: event.outputPath ?? task.hardsubJobs[event.mode]?.outputPath ?? null,
              error: event.error ?? null,
            },
          },
        }
      }),
    })),
  patchClipSplitterSettings: (patch) =>
    set((state) => ({
      clipSplitterSettings: normalizeClipSplitterSettings({
        ...state.clipSplitterSettings,
        ...patch,
      }),
    })),
  setClipSplitterOutputDir: (outputDir) =>
    set((state) => ({
      clipSplitterSettings: normalizeClipSplitterSettings({
        ...state.clipSplitterSettings,
        outputDir,
      }),
    })),
  setClipSplitterSourcePath: (sourcePath) => set({ clipSplitterSourcePath: sourcePath }),
  upsertClipSplitterProgress: (event) =>
    set((state) => ({
      clipSplitterTasks: upsertClipSplitterTask(state.clipSplitterTasks, event),
    })),
  completeClipSplitterTask: (event) =>
    set((state) => ({
      clipSplitterTasks: upsertClipSplitterTask(state.clipSplitterTasks, event),
    })),
  failClipSplitterTask: (event) =>
    set((state) => ({
      clipSplitterTasks: upsertClipSplitterTask(state.clipSplitterTasks, event),
    })),
  setClipFeedbackForTask: (taskId, clipId, label) =>
    set((state) => ({
      // Atualiza somente o clipe alterado para refletir o feedback salvo pelo usuario.
      clipSplitterTasks: state.clipSplitterTasks.map((task) => {
        if (task.id !== taskId) {
          return task
        }

        return {
          ...task,
          clips: task.clips.map((clip) =>
            clip.clipId === clipId
              ? {
                  ...clip,
                  feedbackLabel: label,
                  feedbackUpdatedAt: label ? Date.now() : null,
                }
              : clip,
          ),
        }
      }),
    })),
}))
