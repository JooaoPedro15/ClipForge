import path from 'node:path'

import { app } from 'electron'

// Pasta local do aprendizado de estilo de legenda (fora do repo, por usuario do Windows).
export function getStyleStoreDir() {
  return path.join(app.getPath('userData'), 'subtitle-style')
}
