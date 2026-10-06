// Roda os testes Python com o mesmo Python que o app usa (venv do subtitle-forge).
// Uso: npm run test:py          -> todos os *_test.py
//      npm run test:py -- srt   -> so srt*_test.py
import { spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import path from 'node:path'

// Mesma ordem de resolveSubtitleForgeRoot/resolvePythonCommand (electron/ipc/subtitle.ts).
const roots = [
  process.env.CLIPFORGE_SUBTITLE_FORGE_PATH,
  path.resolve(process.cwd(), '../subtitle-forge'),
  'D:\\Projetos\\subtitle-forge',
].filter(Boolean)

function resolvePython() {
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

const filter = process.argv[2] ?? ''
const python = resolvePython()
const args = ['-m', 'unittest', 'discover', '-s', 'python', '-p', `${filter}*_test.py`]

console.log(`[test:py] ${python} ${args.join(' ')}`)
const result = spawnSync(python, args, {
  stdio: 'inherit',
  env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
})
process.exit(result.status ?? 1)
