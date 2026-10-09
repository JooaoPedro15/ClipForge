// Roda o modulo de cortes pela linha de comando com o mesmo Python e as mesmas DLLs CUDA do app.
// Uso: npm run cortes -- analyze "E:\Bruto\react.mp4" --start 2:24.44 --end 12:54
import { spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import path from 'node:path'

import { resolvePython } from './resolve-python.mjs'

const python = resolvePython()
// Mesmas pastas de resolveNvidiaBinPaths (electron/python/pythonEnv.ts): <venv>/Lib/site-packages/nvidia/<lib>/bin.
const venv = path.dirname(path.dirname(python))
const nvidiaBins = ['cublas', 'cudnn', 'cuda_runtime', 'cuda_nvrtc']
  .map((lib) => path.join(venv, 'Lib', 'site-packages', 'nvidia', lib, 'bin'))
  .filter((dir) => existsSync(dir))

const result = spawnSync(python, ['python/cortes_service.py', ...process.argv.slice(2)], {
  stdio: 'inherit',
  env: {
    ...process.env,
    PYTHONIOENCODING: 'utf-8',
    PATH: [...nvidiaBins, process.env.PATH ?? ''].filter(Boolean).join(path.delimiter),
  },
})
process.exit(result.status ?? 1)
