// Acha o Python que o app usa (venv do subtitle-forge), pros scripts de dev.
import { existsSync } from 'node:fs'
import path from 'node:path'

// Mesma ordem de resolveSubtitleForgeRoot/resolvePythonCommand (electron/ipc/subtitle.ts).
const roots = [
  process.env.CLIPFORGE_SUBTITLE_FORGE_PATH,
  path.resolve(process.cwd(), '../subtitle-forge'),
  'D:\\Projetos\\subtitle-forge',
].filter(Boolean)

export function resolvePython() {
  for (const root of roots) {
    for (const venv of ['.venv', 'venv']) {
      const candidate = path.join(root, venv, 'Scripts', 'python.exe')
      if (existsSync(candidate)) {
        return candidate
      }
    }
  }
  return 'python'
}
