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

  // Live e gameplay longo passam de 1h: "3h 12m" le melhor que "192m 0s".
  if (seconds >= 3600) {
    return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`
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

// Resumo da fila pro cabecalho ("1 rodando, 2 esperando, 1 pronta"), igual nas duas ferramentas.
export function summarizeQueue(tasks: Array<{ status: string }>): string {
  const count = (...statuses: string[]) => tasks.filter((task) => statuses.includes(task.status)).length
  const running = count('processing', 'preparing')
  const waiting = count('queued')
  const done = count('completed')
  return [
    running ? `${running} rodando` : null,
    waiting ? `${waiting} esperando` : null,
    done ? `${done} ${done === 1 ? 'pronta' : 'prontas'}` : null,
  ]
    .filter(Boolean)
    .join(', ')
}
