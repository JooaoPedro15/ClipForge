// Roda o Ruff (lint Python) com o Python do app. Uso: npm run lint:py [-- --fix]
import { spawnSync } from 'node:child_process'

import { resolvePython } from './resolve-python.mjs'

const result = spawnSync(resolvePython(), ['-m', 'ruff', 'check', 'python', ...process.argv.slice(2)], {
  stdio: 'inherit',
})
process.exit(result.status ?? 1)
