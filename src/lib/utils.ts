// Junta classes condicionais sem depender de bibliotecas externas.
export function cn(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(' ')
}

// Detecta se a UI esta rodando dentro do shell Electron com preload exposto.
export function hasClipForgeDesktopBridge(): boolean {
  return typeof window !== 'undefined' && typeof window.clipforge !== 'undefined'
}

// Formata duracoes curtas e longas para cards e listas da interface.
export function formatDuration(seconds: number | null): string {
  if (seconds === null || Number.isNaN(seconds)) {
    return '--'
  }

  if (seconds < 60) {
    return `${seconds.toFixed(1)}s`
  }

  const minutes = Math.floor(seconds / 60)
  const remainingSeconds = Math.round(seconds % 60)
  return `${minutes}m ${remainingSeconds}s`
}

// Exibe horario amigavel de inicio/fim das tarefas.
export function formatTimestamp(timestamp: number | null): string {
  if (!timestamp) {
    return '--'
  }

  return new Intl.DateTimeFormat('pt-BR', {
    hour: '2-digit',
    minute: '2-digit',
  }).format(timestamp)
}

// Traduz o status tecnico da tarefa para um rotulo legivel na UI.
export function formatTaskStatus(status: string): string {
  switch (status) {
    case 'queued':
      return 'Na fila'
    case 'preparing':
      return 'Preparando'
    case 'processing':
      return 'Processando'
    case 'completed':
      return 'Concluída'
    case 'cancelled':
      return 'Cancelada'
    case 'error':
      return 'Erro'
    default:
      return status
  }
}

// Extrai apenas o nome do arquivo a partir de um caminho absoluto.
export function getFileName(filePath: string): string {
  const normalized = filePath.replaceAll('\\', '/')
  const parts = normalized.split('/')
  return parts.at(-1) ?? filePath
}

const LANGUAGE_LABELS: Record<string, string> = {
  pt: 'português',
  en: 'inglês',
  es: 'espanhol',
  fr: 'francês',
  de: 'alemão',
  it: 'italiano',
  ja: 'japonês',
  ko: 'coreano',
  ru: 'russo',
  zh: 'chinês',
}

// Nome do idioma em portugues a partir do codigo do Whisper (cai no codigo se nao conhecer).
export function formatLanguage(code: string): string {
  return LANGUAGE_LABELS[code] ?? code
}
