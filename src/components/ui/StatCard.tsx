import type { ReactNode } from 'react'

import { Card } from '@/components/ui/Card'

interface StatCardProps {
  label: string
  value: string
  hint?: string
  icon?: ReactNode
}

export function StatCard({ label, value, hint, icon }: StatCardProps) {
  return (
    <Card className="min-h-[120px] overflow-hidden">
      {/* Estrutura fixa para metricas curtas exibidas no topo das paginas. */}
      <div className="flex h-full flex-col gap-5">
        <div className="flex items-center justify-between text-text-secondary">
          <span className="text-sm">{label}</span>
          <span className="text-text-muted">{icon}</span>
        </div>

        <div className="space-y-1">
          <p className="text-3xl font-semibold text-text-primary">{value}</p>
          {hint ? <p className="text-sm text-text-secondary">{hint}</p> : null}
        </div>
      </div>
    </Card>
  )
}
