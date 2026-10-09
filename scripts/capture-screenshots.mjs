// Gera as imagens do README: sobe o Vite, abre o app em modo demonstracao numa janela
// escondida do proprio Electron e salva os PNG em docs/screenshots.
// Uso: npm run screenshots
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { app, BrowserWindow } from 'electron'
import { createServer } from 'vite'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const outDir = path.join(root, 'docs', 'screenshots')

// Tamanho da janela do app na foto; a escala 2 deixa a imagem nitida no LinkedIn.
const VIEWPORT = { width: 1440, height: 900, deviceScaleFactor: 2, mobile: false }

// selector = recorta so aquele elemento (o monitor de previa vira imagem propria).
const shots = [
  { file: 'legendas.png', query: '?demo=subtitle-forge' },
  { file: 'legendas-shorts.png', query: '?demo=subtitle-forge&format=shorts' },
  { file: 'pre-edicao.png', query: '?demo=clip-splitter' },
  { file: 'monitor.png', query: '?demo=subtitle-forge&format=shorts', selector: '[aria-label="Inspetor"] figure' },
]

// Na primeira visita o Vite otimiza dependencias e recarrega a pagina, o que derruba o
// loadURL em andamento; uma segunda tentativa ja encontra tudo pronto.
async function load(win, url) {
  try {
    await win.loadURL(url)
  } catch {
    await win.loadURL(url)
  }
  // Espera as fontes do Google e a primeira pintura antes de fotografar.
  await win.webContents.executeJavaScript('document.fonts.ready.then(() => new Promise((r) => setTimeout(r, 900)))')
}

async function clipFor(win, selector) {
  return win.webContents.executeJavaScript(`(() => {
    const rect = document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect()
    return { x: rect.x, y: rect.y, width: rect.width, height: rect.height, scale: 1 }
  })()`)
}

app.whenReady().then(async () => {
  const server = await createServer({ root, logLevel: 'error', server: { port: 5199 } })
  await server.listen()
  const baseUrl = server.resolvedUrls.local[0]
  await mkdir(outDir, { recursive: true })

  const win = new BrowserWindow({ width: 1280, height: 800, show: false, frame: false, backgroundColor: '#141414' })
  // O protocolo do DevTools emula a tela e fotografa sem depender do monitor de quem roda.
  // Ele so responde depois que a janela tem uma pagina, dai o about:blank antes.
  await win.loadURL('about:blank')
  const cdp = win.webContents.debugger
  cdp.attach('1.3')
  await cdp.sendCommand('Emulation.setDeviceMetricsOverride', VIEWPORT)

  try {
    for (const shot of shots) {
      await load(win, new URL(shot.query, baseUrl).toString())
      const clip = shot.selector ? await clipFor(win, shot.selector) : undefined
      const { data } = await cdp.sendCommand('Page.captureScreenshot', { format: 'png', clip })
      await writeFile(path.join(outDir, shot.file), Buffer.from(data, 'base64'))
      console.log(`salvo docs/screenshots/${shot.file}`)
    }
  } finally {
    cdp.detach()
    await server.close()
    app.quit()
  }
})
