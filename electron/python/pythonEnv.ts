// Acha o projeto Python, o interpretador do venv e as DLLs CUDA. Sem depender do Electron.
import { existsSync } from 'node:fs'
import path from 'node:path'

const VENV_DIRS = ['.venv', 'venv']
const NVIDIA_LIBS = ['cublas', 'cudnn', 'cuda_runtime', 'cuda_nvrtc']

function venvPython(root: string, venv: string) {
  return path.join(root, venv, 'Scripts', 'python.exe')
}

// Primeira pasta candidata que tem um venv ou o arquivo marcador do projeto.
export function resolveProjectRoot(candidates: Array<string | undefined>, markerFile: string): string | null {
  return (
    candidates
      .filter((candidate): candidate is string => Boolean(candidate))
      .find(
        (candidate) =>
          VENV_DIRS.some((venv) => existsSync(venvPython(candidate, venv))) || existsSync(path.join(candidate, markerFile)),
      ) ?? null
  )
}

// Prefere o Python do venv local, mas ainda permite fallback para o python do sistema.
export function resolvePythonCommand(root: string) {
  for (const venv of VENV_DIRS) {
    const candidate = venvPython(root, venv)
    if (existsSync(candidate)) {
      return { command: candidate, args: [] as string[] }
    }
  }

  return { command: 'python', args: [] as string[] }
}

// Pastas bin das libs NVIDIA instaladas no venv (o processo Python precisa delas no PATH pra usar CUDA).
export function resolveNvidiaBinPaths(root: string): string[] {
  return VENV_DIRS.flatMap((venv) =>
    NVIDIA_LIBS.map((lib) => path.join(root, venv, 'Lib', 'site-packages', 'nvidia', lib, 'bin')),
  ).filter((candidate) => existsSync(candidate))
}

// Primeiro script que existe; `checked` serve pra mensagem de erro quando nenhum existe.
export function resolveScriptPath(candidates: string[]): { scriptPath: string | null; checked: string[] } {
  return { scriptPath: candidates.find((candidate) => existsSync(candidate)) ?? null, checked: candidates }
}
