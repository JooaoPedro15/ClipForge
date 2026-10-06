// Lint do TypeScript/React (src/, electron/, scripts/). Rodar: npm run lint:ts
import js from '@eslint/js'
import { defineConfig, globalIgnores } from 'eslint/config'
import reactHooks from 'eslint-plugin-react-hooks'
import globals from 'globals'
import tseslint from 'typescript-eslint'

export default defineConfig([
  globalIgnores(['dist', 'dist-electron', 'node_modules', 'python', 'resources']),
  {
    // Renderer (React no navegador do Electron).
    files: ['src/**/*.{ts,tsx}'],
    extends: [js.configs.recommended, tseslint.configs.recommended, reactHooks.configs.flat.recommended],
    languageOptions: { globals: globals.browser },
  },
  {
    // Processo principal do Electron, scripts de dev e configs: rodam no Node.
    files: ['electron/**/*.ts', 'scripts/**/*.mjs', '*.config.{js,ts}'],
    extends: [js.configs.recommended, tseslint.configs.recommended],
    languageOptions: { globals: globals.node },
  },
])
