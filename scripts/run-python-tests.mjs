// Roda os testes Python com o mesmo Python que o app usa (venv do subtitle-forge).
// Uso: npm run test:py          -> todos os *_test.py
//      npm run test:py -- srt   -> so srt*_test.py
import { spawnSync } from 'node:child_process'

import { resolvePython } from './resolve-python.mjs'

const filter = process.argv[2] ?? ''
const python = resolvePython()
const args = ['-m', 'unittest', 'discover', '-s', 'python', '-p', `${filter}*_test.py`]

console.log(`[test:py] ${python} ${args.join(' ')}`)
const result = spawnSync(python, args, {
  stdio: 'inherit',
  env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
})
process.exit(result.status ?? 1)
