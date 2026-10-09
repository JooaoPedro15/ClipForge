import type { ReactNode } from 'react'

interface WorkspaceProps {
  title: string
  description: string
  inspector: ReactNode
  children: ReactNode
}

// Area de trabalho de cada ferramenta: conteudo no centro e Inspetor fixo a direita,
// como o painel de propriedades de um editor de video. Cada lado rola sozinho.
export function Workspace({ title, description, inspector, children }: WorkspaceProps) {
  return (
    <div className="flex h-full min-h-0">
      <div className="min-w-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-4xl space-y-5 px-6 py-6">
          <header>
            <h1 className="text-[22px] font-semibold tracking-tight text-text-primary">{title}</h1>
            <p className="mt-1 text-sm text-text-secondary">{description}</p>
          </header>
          {children}
        </div>
      </div>

      <aside aria-label="Inspetor" className="w-[340px] shrink-0 overflow-y-auto border-l border-line bg-panel">
        {inspector}
      </aside>
    </div>
  )
}
