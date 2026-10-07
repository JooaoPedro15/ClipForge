import { app, BrowserWindow, ipcMain, dialog, shell } from 'electron'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { registerClipSplitterHandlers } from './ipc/clipSplitter.js'
import { registerSubtitleHandlers } from './ipc/subtitle.js'
import { registerHardsubHandlers } from './ipc/subtitleBurn.js'
import { registerSubtitleStyleHandlers } from './ipc/subtitleStyle.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// Detecta se o app deve abrir a URL do Vite ou os arquivos empacotados.
const isDev = !app.isPackaged
const VITE_DEV_URL = 'http://localhost:5173'

let mainWindow: BrowserWindow | null = null

function createWindow(): void {
  // Cria a janela principal do Electron com preload isolado e barra customizada.
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    frame: false,
    titleBarStyle: 'hidden',
    icon: path.join(__dirname, '..', '..', 'resources', 'icon.ico'),
    backgroundColor: '#050505',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  })

  if (isDev) {
    // Em desenvolvimento o renderer vem do servidor Vite.
    mainWindow.loadURL(VITE_DEV_URL)
    mainWindow.webContents.openDevTools()
  } else {
    // Em producao carrega o build estatico do frontend.
    mainWindow.loadFile(path.join(__dirname, '../../dist/index.html'))
  }

  // Repassa logs do renderer para facilitar debug no terminal principal.
  mainWindow.webContents.on('console-message', (_event, level, message, line, sourceId) => {
    const prefix = `[renderer:${level}]`
    console.log(prefix, message, sourceId ? `(${sourceId}:${line})` : '')
  })

  mainWindow.webContents.on('did-fail-load', (_event, errorCode, errorDescription, validatedURL) => {
    console.error('[renderer:did-fail-load]', errorCode, errorDescription, validatedURL)
  })

  mainWindow.webContents.on('render-process-gone', (_event, details) => {
    console.error('[renderer:gone]', details.reason, details.exitCode)
  })
}

// Window control IPC handlers
ipcMain.handle('window:minimize', () => mainWindow?.minimize())
ipcMain.handle('window:maximize', () => {
  if (mainWindow?.isMaximized()) mainWindow.unmaximize()
  else mainWindow?.maximize()
})
ipcMain.handle('window:close', () => mainWindow?.close())

// Dialog IPC handlers usados pelo renderer para selecionar arquivos e diretorios.
ipcMain.handle('dialog:openFiles', async (_event, filters: { name: string; extensions: string[] }[]) => {
  if (!mainWindow) return []
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openFile', 'multiSelections'],
    filters,
  })
  return result.filePaths
})

ipcMain.handle('dialog:openDirectory', async () => {
  if (!mainWindow) return null
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory', 'createDirectory'],
  })
  return result.canceled ? null : (result.filePaths[0] ?? null)
})

// Shell IPC handler para revelar arquivos e pastas no explorador do sistema.
ipcMain.handle('shell:showItemInFolder', (_event, filePath: string) => {
  shell.showItemInFolder(filePath)
})

ipcMain.handle('shell:openPath', async (_event, filePath: string) => {
  return shell.openPath(filePath)
})

// Registra os namespaces de IPC que gerenciam filas e processos filhos.
registerSubtitleHandlers()
registerHardsubHandlers()
registerSubtitleStyleHandlers()
registerClipSplitterHandlers()

// Cria a janela quando o Electron estiver pronto e reabre no macOS ao reativar.
app.whenReady().then(() => {
  createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

// Fecha a aplicacao quando nao houver mais janelas abertas fora do macOS.
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
