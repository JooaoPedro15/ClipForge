// Grava um video curto do app (pro LinkedIn): sobe o Vite, abre o modo demonstracao numa
// janela offscreen do Electron, roda um roteiro de cliques e manda cada quadro pro ffmpeg.
// Uso: npm run video  (saida em docs/media/clipforge-demo.mp4, fora do git como todo .mp4)
import { spawn, spawnSync } from 'node:child_process'
import { once } from 'node:events'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { app, BrowserWindow } from 'electron'
import { createServer } from 'vite'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const output = path.join(root, 'docs', 'media', 'clipforge-demo.mp4')

// A pagina tem 1440x810 (mesmo layout dos prints) e renderiza em escala 4/3, saindo em
// 1920x1080, o formato que o LinkedIn mais aceita bem. Janela maior que a tela nao serve:
// o Windows corta na area util, mesmo offscreen.
const PAGE = { width: 1440, height: 810 }
const SCALE = 1920 / 1440
const FPS = 30

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2)

// Mesmo lugar que o app procura o ffmpeg: variavel, PATH ou C:\ffmpeg\bin.
function findFfmpeg() {
  const candidates = [process.env.FFMPEG_PATH, 'ffmpeg', 'C:\\ffmpeg\\bin\\ffmpeg.exe'].filter(Boolean)
  const found = candidates.find((candidate) => spawnSync(candidate, ['-version']).status === 0)
  if (!found) {
    throw new Error('ffmpeg nao encontrado. Instale ou defina FFMPEG_PATH.')
  }
  return found
}

// Cursor desenhado na pagina: a janela offscreen nao tem ponteiro do sistema pra filmar.
const CURSOR_SCRIPT = `(() => {
  const cursor = document.createElement('div')
  cursor.innerHTML = '<svg width="22" height="22" viewBox="0 0 24 24"><path d="M4 2l16 10-7 1.5L9.5 21z" fill="#fff" stroke="#000" stroke-width="1.5" stroke-linejoin="round"/></svg>'
  Object.assign(cursor.style, { position: 'fixed', left: 0, top: 0, zIndex: 99999, pointerEvents: 'none', transform: 'translate(-100px,-100px)' })
  const ring = document.createElement('div')
  Object.assign(ring.style, { position: 'fixed', width: '28px', height: '28px', margin: '-14px 0 0 -14px', borderRadius: '50%', border: '2px solid #ffd60a', zIndex: 99998, pointerEvents: 'none', opacity: 0 })
  document.body.append(ring, cursor)
  addEventListener('mousemove', (e) => { cursor.style.transform = 'translate(' + (e.clientX - 3) + 'px,' + (e.clientY - 2) + 'px)' }, true)
  addEventListener('mousedown', (e) => {
    Object.assign(ring.style, { left: e.clientX + 'px', top: e.clientY + 'px' })
    ring.animate([{ opacity: 1, transform: 'scale(0.5)' }, { opacity: 0, transform: 'scale(1.6)' }], { duration: 450, easing: 'ease-out' })
  }, true)
})()`

// Acha o elemento pelo texto/seletor e devolve o centro em coordenadas da pagina (CSS px).
async function centerOf(win, finder) {
  // Rola com suavidade se o alvo estiver na borda e so mede depois que a rolagem acaba.
  const point = await win.webContents.executeJavaScript(`new Promise((resolve) => {
    const el = (${finder})()
    if (!el) return resolve(null)
    el.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    setTimeout(() => {
      const r = el.getBoundingClientRect()
      resolve({ x: r.x + r.width / 2, y: r.y + r.height / 2 })
    }, 450)
  })`)
  if (!point) {
    throw new Error(`Elemento do roteiro nao encontrado: ${finder}`)
  }
  return point
}

const byText = (selector, text) => `() => [...document.querySelectorAll(${JSON.stringify(selector)})].find((el) => el.textContent.trim() === ${JSON.stringify(text)})`
const bySelector = (selector) => `() => document.querySelector(${JSON.stringify(selector)})`

// Movimento suave e clique com eventos de mouse de verdade (hover e foco funcionam).
// Com escala offscreen o sendInputEvent recebe pixels da saida, nao da pagina: multiplica.
function createMouse(win) {
  let position = { x: 700, y: 520 }
  const send = (event) =>
    win.webContents.sendInputEvent({ ...event, x: Math.round(position.x * SCALE), y: Math.round(position.y * SCALE) })
  return {
    async moveTo(target, duration = 650) {
      const from = position
      const steps = Math.max(1, Math.round(duration / 16))
      for (let step = 1; step <= steps; step += 1) {
        const t = ease(step / steps)
        position = { x: from.x + (target.x - from.x) * t, y: from.y + (target.y - from.y) * t }
        send({ type: 'mouseMove' })
        await sleep(16)
      }
    },
    async click() {
      send({ type: 'mouseDown', button: 'left', clickCount: 1 })
      await sleep(70)
      send({ type: 'mouseUp', button: 'left', clickCount: 1 })
    },
    park: () => send({ type: 'mouseMove' }),
  }
}

// O roteiro: mexe nas opcoes que mudam o monitor e depois mostra o diagrama de pausas.
const SCENARIO = [
  { pause: 1800 },
  { target: byText('[role=radio]', 'Shorts 9:16'), pause: 1900 },
  { target: byText('[role=radio]', 'MAIÚSCULAS'), pause: 1900 },
  { target: `() => document.getElementById([...document.querySelectorAll('label')].find((l) => l.textContent.includes('Sem pontuação')).htmlFor)`, pause: 1700 },
  // O stepper fica na borda de baixo: o Inspetor rola ate ele e depois volta, pro monitor
  // nao ficar cortado no resto do video.
  { target: bySelector('[aria-label="Diminuir palavras por legenda"]'), pause: 1900 },
  { scrollTop: '[aria-label="Inspetor"]', pause: 700 },
  { target: byText('nav button', 'Pré-edição'), pause: 1500 },
  { target: byText('[role=radio]', 'Forte'), pause: 1700 },
  { target: byText('[role=radio]', 'Leve'), pause: 1700 },
  { target: byText('nav button', 'Legendas'), pause: 2000 },
]

async function record() {
  const ffmpegPath = findFfmpeg()
  const server = await createServer({ root, logLevel: 'error', server: { port: 5198 } })
  await server.listen()
  await mkdir(path.dirname(output), { recursive: true })

  // Offscreen: o Chromium desenha sem mostrar janela e entrega cada quadro no evento paint.
  const win = new BrowserWindow({
    ...PAGE,
    show: false,
    frame: false,
    backgroundColor: '#141414',
    webPreferences: { offscreen: { deviceScaleFactor: SCALE }, backgroundThrottling: false },
  })
  win.webContents.setFrameRate(FPS)
  let latest = null
  let frameSize = null
  win.webContents.on('paint', (_event, _dirty, image) => {
    latest = image
    frameSize ??= image.getSize()
  })

  const url = new URL('?demo=subtitle-forge&animate', server.resolvedUrls.local[0]).toString()
  try {
    await win.loadURL(url)
  } catch {
    // Na primeira visita o Vite otimiza dependencias e recarrega a pagina.
    await win.loadURL(url)
  }
  await win.webContents.executeJavaScript('document.fonts.ready.then(() => new Promise((r) => setTimeout(r, 800)))')
  await win.webContents.executeJavaScript(CURSOR_SCRIPT)
  const mouse = createMouse(win)
  mouse.park()
  await sleep(300)

  const ffmpeg = spawn(
    ffmpegPath,
    ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(FPS), '-c:v', 'mjpeg', '-i', '-',
      // Garante 1920x1080 mesmo se a escala offscreen (experimental) nao for aplicada, e passa
      // a cor da faixa do JPEG (pc) pra faixa de video (tv), que todo player le certo.
      '-vf', 'scale=1920:1080:flags=lanczos:in_range=pc:out_range=tv,format=yuv420p', '-color_range', 'tv',
      '-c:v', 'libx264', '-crf', '18', '-preset', 'medium', '-movflags', '+faststart', output],
    { stdio: ['pipe', 'ignore', 'inherit'] },
  )

  // O paint so chega quando algo muda; o relogio decide quantos quadros escrever, repetindo
  // o ultimo quando a tela esta parada. Assim o video tem a duracao real do roteiro.
  const startedAt = Date.now()
  let written = 0
  const recorder = setInterval(() => {
    const due = Math.floor(((Date.now() - startedAt) / 1000) * FPS)
    if (!latest || written >= due) return
    const frame = latest.toJPEG(92)
    while (written < due) {
      ffmpeg.stdin.write(frame)
      written += 1
    }
  }, 1000 / FPS / 2)

  try {
    for (const step of SCENARIO) {
      if (step.scrollTop) {
        await win.webContents.executeJavaScript(`document.querySelector(${JSON.stringify(step.scrollTop)}).scrollTo({ top: 0, behavior: 'smooth' })`)
      }
      if (step.target) {
        await mouse.moveTo(await centerOf(win, step.target))
        await sleep(120)
        await mouse.click()
      }
      await sleep(step.pause)
    }
  } finally {
    clearInterval(recorder)
    ffmpeg.stdin.end()
    await once(ffmpeg, 'close')
    await server.close()
    console.log(`salvo ${path.relative(root, output)} (${(written / FPS).toFixed(1)}s, ${written} quadros, render ${frameSize?.width}x${frameSize?.height})`)
  }
}

app.whenReady().then(async () => {
  try {
    await record()
    app.quit()
  } catch (error) {
    console.error(`Gravacao falhou: ${error.message}`)
    app.exit(1)
  }
})
