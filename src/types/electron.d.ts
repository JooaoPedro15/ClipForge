import type {
  ClipSplitterDoneEvent,
  ClipSplitterErrorEvent,
  ClipSplitterOptions,
  ClipSplitterProgressEvent,
} from './clipSplitter'
import type {
  HardsubEvent,
  HardsubFormat,
  HardsubMode,
  SubtitleDoneEvent,
  SubtitleErrorEvent,
  SubtitleProgressEvent,
  SubtitleTaskOptions,
} from './subtitle'
import type {
  StyleForgetReport,
  StyleLearnRequest,
  StyleLibrary,
  StyleProgressEvent,
  StyleReport,
  StyleRunResult,
} from './subtitleStyle'

declare global {
  interface Window {
    // API exposta pelo preload para o renderer conversar com o processo principal.
    clipforge: {
      window: {
        // Controles da janela frameless do Electron.
        minimize: () => Promise<void>
        maximize: () => Promise<void>
        close: () => Promise<void>
        // Traz a janela pra frente (clique no aviso de tarefa pronta).
        focus: () => Promise<void>
        // Pisca o icone na barra de tarefas ate a janela voltar ao foco.
        requestAttention: () => Promise<void>
      }
      dialog: {
        // Dialogos nativos usados para selecionar arquivos e diretorios.
        openFiles: (filters: { name: string; extensions: string[] }[]) => Promise<string[]>
        openDirectory: () => Promise<string | null>
        getPathForFile: (file: File) => string
      }
      shell: {
        // Acoes de sistema operacional expostas de forma segura para a UI.
        showItemInFolder: (filePath: string) => Promise<void>
        openPath: (filePath: string) => Promise<string>
      }
      subtitle: {
        // Ponte entre o renderer e a fila de transcricao do Electron.
        process: (filePath: string, options: Partial<SubtitleTaskOptions>) => Promise<string>
        cancel: (taskId: string) => Promise<boolean>
        onProgress: (cb: (data: SubtitleProgressEvent) => void) => () => void
        onDone: (cb: (data: SubtitleDoneEvent) => void) => () => void
        onError: (cb: (data: SubtitleErrorEvent) => void) => () => void
        burn: (taskId: string, mode: HardsubMode, format: HardsubFormat) => Promise<string>
        onBurnProgress: (cb: (data: HardsubEvent) => void) => () => void
        onBurnDone: (cb: (data: HardsubEvent) => void) => () => void
        onBurnError: (cb: (data: HardsubEvent) => void) => () => void
      }
      subtitleStyle: {
        // Ponte com o aprendizado do estilo de legenda (ensinar entra na fila unica de GPU).
        list: () => Promise<StyleLibrary>
        learn: (request: StyleLearnRequest) => Promise<StyleRunResult<StyleReport>>
        forget: (videoId: string) => Promise<StyleRunResult<StyleForgetReport>>
        onProgress: (cb: (data: StyleProgressEvent) => void) => () => void
      }
      clipSplitter: {
        // Ponte entre o renderer e o pipeline de corte/exportacao.
        process: (sourcePath: string, options: Partial<ClipSplitterOptions>) => Promise<string>
        cancel: (taskId: string) => Promise<boolean>
        onProgress: (cb: (data: ClipSplitterProgressEvent) => void) => () => void
        onDone: (cb: (data: ClipSplitterDoneEvent) => void) => () => void
        onError: (cb: (data: ClipSplitterErrorEvent) => void) => () => void
      }
    }
  }
}

export {}
