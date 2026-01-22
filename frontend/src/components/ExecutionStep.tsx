import { useEffect, useState } from 'react'
import { clsx } from 'clsx'
import {
  AlertCircle,
  CheckCircle,
  ChevronDown,
  ChevronRight,
  Circle,
  Loader2,
  MinusCircle,
  Terminal,
  XCircle,
} from 'lucide-react'
import type { PlanStep } from '../types/dashboard'

interface ExecutionStepProps {
  step: PlanStep
  output?: string[]
  isActive?: boolean
}

const statusMap = {
  pending: {
    icon: Circle,
    color: 'text-gray-400',
    bg: 'bg-white border-gray-200',
    label: 'Pending',
  },
  running: {
    icon: Loader2,
    color: 'text-blue-500',
    bg: 'bg-blue-50 border-blue-200',
    label: 'Running',
  },
  completed: {
    icon: CheckCircle,
    color: 'text-green-500',
    bg: 'bg-green-50 border-green-200',
    label: 'Completed',
  },
  failed: {
    icon: XCircle,
    color: 'text-red-500',
    bg: 'bg-red-50 border-red-200',
    label: 'Failed',
  },
  skipped: {
    icon: MinusCircle,
    color: 'text-gray-500',
    bg: 'bg-gray-50 border-gray-200',
    label: 'Skipped',
  },
} as const

export default function ExecutionStep({ step, output = [], isActive = false }: ExecutionStepProps) {
  const [expanded, setExpanded] = useState(isActive || step.status === 'failed')
  const hasDetails = Boolean(output.length || step.output || step.error)
  const config = statusMap[step.status] ?? statusMap.pending

  useEffect(() => {
    if (isActive) {
      setExpanded(true)
    }
  }, [isActive])

  return (
    <div
      data-step-index={step.index}
      className={clsx(
        'rounded-xl border transition-shadow',
        config.bg,
        isActive && 'ring-2 ring-blue-400 shadow-lg'
      )}
    >
      <div
        className={clsx(
          'flex cursor-pointer items-center gap-4 p-4',
          hasDetails && 'hover:bg-black/5'
        )}
        onClick={() => hasDetails && setExpanded((prev) => !prev)}
      >
        <div className={clsx('flex h-10 w-10 items-center justify-center rounded-2xl', config.color)}>
          <config.icon className={clsx('h-5 w-5', step.status === 'running' && 'animate-spin')} />
        </div>
        <div className="flex flex-1 flex-col gap-1">
          <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-gray-500">
            <span>Step {step.index + 1}</span>
            <span className="rounded-full bg-white px-2 py-0.5 text-[11px] font-semibold text-gray-700">
              {config.label}
            </span>
            {step.durationMs && (
              <span className="text-[11px] text-gray-400">
                {(step.durationMs / 1000).toFixed(1)}s
              </span>
            )}
          </div>
          <p className="text-sm font-semibold text-gray-900">{step.name}</p>
          <p className="text-xs text-gray-500">{step.description}</p>
        </div>
        {hasDetails && (
          <div className="text-gray-400">
            {expanded ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )}
          </div>
        )}
      </div>

      {expanded && hasDetails && (
        <div className="space-y-3 border-t border-gray-200 bg-gray-900/80 p-4 text-xs text-white">
          {output.length > 0 && (
            <div>
              <div className="flex items-center gap-2 text-gray-300">
                <Terminal className="h-4 w-4" />
                <span>Live Output</span>
              </div>
              <pre className="mt-2 max-h-48 overflow-y-auto whitespace-pre-wrap font-mono text-[11px]">
                {output.join('')}
              </pre>
            </div>
          )}

          {step.output && (
            <div>
              <div className="flex items-center gap-2 text-gray-300">
                <Terminal className="h-4 w-4" />
                <span>Final Output</span>
              </div>
              <pre className="mt-2 max-h-32 overflow-y-auto whitespace-pre-wrap font-mono text-[11px]">
                {step.output}
              </pre>
            </div>
          )}

          {step.error && (
            <div className="rounded-lg border border-red-500/60 bg-red-900/60 p-3">
              <div className="flex items-center gap-2 text-red-300">
                <AlertCircle className="h-4 w-4" />
                <span>Error</span>
              </div>
              <pre className="mt-2 max-h-32 overflow-y-auto whitespace-pre-wrap font-mono text-[11px] text-red-100">
                {step.error}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
