// Processo filho falso: imita o retorno do spawn pros testes dos IPCs, sem rodar Python.
// stdout/stderr emitem 'data' de forma sincrona, entao a ordem dos eventos e deterministica.
import { EventEmitter } from 'node:events'

interface FakeStream extends EventEmitter {
  setEncoding: (encoding: string) => FakeStream
}

export interface FakeChild extends EventEmitter {
  command: string
  args: string[]
  options: { cwd?: string; env?: Record<string, string | undefined> }
  stdout: FakeStream
  stderr: FakeStream
  killed: boolean
  kill: () => boolean
  emitStdout: (text: string) => void
  emitStderr: (text: string) => void
  close: (code: number | null) => void
}

function createStream(): FakeStream {
  const stream = new EventEmitter() as FakeStream
  stream.setEncoding = () => stream
  return stream
}

export function createFakeChild(command: string, args: string[], options: FakeChild['options']): FakeChild {
  const child = new EventEmitter() as FakeChild
  child.command = command
  child.args = args
  child.options = options
  child.stdout = createStream()
  child.stderr = createStream()
  child.killed = false
  // Como no Node real, kill() so pede pra encerrar; o teste decide quando chega o 'close'.
  child.kill = () => {
    child.killed = true
    return true
  }
  child.emitStdout = (text) => {
    child.stdout.emit('data', text)
  }
  child.emitStderr = (text) => {
    child.stderr.emit('data', text)
  }
  child.close = (code) => {
    child.emit('close', code)
  }
  return child
}
