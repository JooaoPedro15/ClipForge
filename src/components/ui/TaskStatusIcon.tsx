import { CircleAlert, CircleCheck, CircleSlash, Clock3 } from 'lucide-react'

import { cn } from '@/lib/utils'

type TaskStatus = 'queued' | 'preparing' | 'processing' | 'completed' | 'error' | 'cancelled'

interface TaskStatusIconProps {
  status: TaskStatus
  progress: number | null
}

const RADIUS = 7
const CIRCUMFERENCE = 2 * Math.PI * RADIUS

// Estado da tarefa num icone so. Rodando vira um anel amarelo que enche com o progresso;
// sem porcentagem ainda, o anel gira.
export function TaskStatusIcon({ status, progress }: TaskStatusIconProps) {
  const label = { queued: 'Na fila', preparing: 'Preparando', processing: 'Processando', completed: 'Pronto', error: 'Erro', cancelled: 'Cancelado' }[status]

  if (status === 'processing' || status === 'preparing') {
    const known = progress !== null
    const offset = known ? CIRCUMFERENCE * (1 - Math.min(100, progress) / 100) : CIRCUMFERENCE * 0.7
    return (
      <svg aria-label={label} className={cn('h-[18px] w-[18px] shrink-0 -rotate-90', !known && 'animate-spin')} role="img" viewBox="0 0 18 18">
        <circle className="stroke-raised" cx="9" cy="9" fill="none" r={RADIUS} strokeWidth="2.5" />
        <circle
          className="stroke-accent transition-[stroke-dashoffset] duration-300"
          cx="9"
          cy="9"
          fill="none"
          r={RADIUS}
          strokeDasharray={CIRCUMFERENCE}
          strokeDashoffset={offset}
          strokeLinecap="round"
          strokeWidth="2.5"
        />
      </svg>
    )
  }

  const Icon = { queued: Clock3, completed: CircleCheck, error: CircleAlert, cancelled: CircleSlash }[status]
  const tone = { queued: 'text-text-muted', completed: 'text-status-green', error: 'text-status-red', cancelled: 'text-text-muted' }[status]
  return <Icon aria-label={label} className={cn('h-[18px] w-[18px] shrink-0', tone)} role="img" strokeWidth={2} />
}

// Barra fina de progresso; amarela porque so aparece no que esta rodando agora.
export function ThinProgress({ value }: { value: number | null }) {
  return (
    <div className="h-[3px] overflow-hidden rounded-full bg-raised">
      <div
        className={cn('h-full rounded-full bg-accent transition-[width] duration-300', value === null && 'w-1/4 animate-pulse')}
        style={value === null ? undefined : { width: `${Math.max(2, value)}%` }}
      />
    </div>
  )
}
