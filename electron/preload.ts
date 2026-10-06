import { contextBridge, ipcRenderer, webUtils } from 'electron'

// API segura exposta para o renderer acessar janelas, dialogs e filas sem habilitar Node direto.
const api = {
  window: {
    minimize: () => ipcRenderer.invoke('window:minimize'),
    maximize: () => ipcRenderer.invoke('window:maximize'),
    close: () => ipcRenderer.invoke('window:close'),
  },
  dialog: {
    // Encapsula os dialogs nativos e a recuperacao do path real de um File do browser.
    openFiles: (filters: { name: string; extensions: string[] }[]) =>
      ipcRenderer.invoke('dialog:openFiles', filters),
    openDirectory: () => ipcRenderer.invoke('dialog:openDirectory'),
    getPathForFile: (file: File) => webUtils.getPathForFile(file),
  },
  shell: {
    // Revela arquivos e pastas no explorador do sistema operacional.
    showItemInFolder: (filePath: string) =>
      ipcRenderer.invoke('shell:showItemInFolder', filePath),
    openPath: (filePath: string) => ipcRenderer.invoke('shell:openPath', filePath),
  },
  subtitle: {
    // Namespace dedicado ao workflow de transcricao sequencial.
    process: (filePath: string, options: Record<string, unknown>) =>
      ipcRenderer.invoke('subtitle:process', filePath, options),
    cancel: (taskId: string) => ipcRenderer.invoke('subtitle:cancel', taskId),
    onProgress: (cb: (data: unknown) => void) => {
      const listener = (_event: unknown, data: unknown) => cb(data)
      ipcRenderer.on('subtitle:progress', listener)
      return () => {
        ipcRenderer.removeListener('subtitle:progress', listener)
      }
    },
    onDone: (cb: (data: unknown) => void) => {
      const listener = (_event: unknown, data: unknown) => cb(data)
      ipcRenderer.on('subtitle:done', listener)
      return () => {
        ipcRenderer.removeListener('subtitle:done', listener)
      }
    },
    onError: (cb: (data: unknown) => void) => {
      const listener = (_event: unknown, data: unknown) => cb(data)
      ipcRenderer.on('subtitle:error', listener)
      return () => {
        ipcRenderer.removeListener('subtitle:error', listener)
      }
    },
    burn: (taskId: string, mode: string, format: string) =>
      ipcRenderer.invoke('subtitle:burn', taskId, mode, format),
    onBurnProgress: (cb: (data: unknown) => void) => {
      const listener = (_event: unknown, data: unknown) => cb(data)
      ipcRenderer.on('subtitle:burn-progress', listener)
      return () => {
        ipcRenderer.removeListener('subtitle:burn-progress', listener)
      }
    },
    onBurnDone: (cb: (data: unknown) => void) => {
      const listener = (_event: unknown, data: unknown) => cb(data)
      ipcRenderer.on('subtitle:burn-done', listener)
      return () => {
        ipcRenderer.removeListener('subtitle:burn-done', listener)
      }
    },
    onBurnError: (cb: (data: unknown) => void) => {
      const listener = (_event: unknown, data: unknown) => cb(data)
      ipcRenderer.on('subtitle:burn-error', listener)
      return () => {
        ipcRenderer.removeListener('subtitle:burn-error', listener)
      }
    },
  },
  clipSplitter: {
    // Namespace dedicado ao workflow do Pre-Editor.
    process: (sourcePath: string, options: Record<string, unknown>) =>
      ipcRenderer.invoke('clipSplitter:process', sourcePath, options),
    cancel: (taskId: string) => ipcRenderer.invoke('clipSplitter:cancel', taskId),
    onProgress: (cb: (data: unknown) => void) => {
      const listener = (_event: unknown, data: unknown) => cb(data)
      ipcRenderer.on('clipSplitter:progress', listener)
      return () => {
        ipcRenderer.removeListener('clipSplitter:progress', listener)
      }
    },
    onDone: (cb: (data: unknown) => void) => {
      const listener = (_event: unknown, data: unknown) => cb(data)
      ipcRenderer.on('clipSplitter:done', listener)
      return () => {
        ipcRenderer.removeListener('clipSplitter:done', listener)
      }
    },
    onError: (cb: (data: unknown) => void) => {
      const listener = (_event: unknown, data: unknown) => cb(data)
      ipcRenderer.on('clipSplitter:error', listener)
      return () => {
        ipcRenderer.removeListener('clipSplitter:error', listener)
      }
    },
  },
} as const

// Injeta a API no objeto window do renderer.
contextBridge.exposeInMainWorld('clipforge', api)

export type ClipForgeAPI = typeof api
