import { useEffect, useMemo, useRef } from 'react'
import { clsx } from 'clsx'
import { AlertCircle, Loader2, StopCircle } from 'lucide-react'
import type { PlanView } from '../types/dashboard'
import { useExecution } from '../hooks/useExecution'
import ExecutionStep from './ExecutionStep'
import ExecutionSummary from './ExecutionSummary'

interface ExecutionMonitorProps {
  plan: PlanView
  sessionId: string
  onComplete: () => void
}

export default function ExecutionMonitor({ plan, sessionId, onComplete }: ExecutionMonitorProps) {
  const execution = useExecution(sessionId)
  const containerRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    execution.startExecution(plan)
    return () => {
      execution.clearExecution()
    }
  }, [plan.planId])

  const completedSteps = execution.steps.filter((step) => step.status === 'completed').length
  const totalSteps = Math.max(execution.steps.length, plan.steps.length)

  const logs = useMemo(() => Object.values(execution.stepOutputs).flat(), [execution.stepOutputs])

  const progress = totalSteps === 0 ? 0 : (completedSteps / totalSteps) * 100

  const activeStepIndex = execution.steps.findIndex((step) => step.status === 'running')

  useEffect(() => {
    if (activeStepIndex === -1) {
      return
    }
    const container = containerRef.current
    if (!container) {
      return
    }
    const node = container.querySelector<HTMLElement>(`[data-step-index="${activeStepIndex}"]`)
    node?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [activeStepIndex])

  const copyLogs = async () => {
    const payload = logs.length ? logs.join('\n') : 'No logs yet.'
    try {
      await navigator.clipboard.writeText(payload)
    } catch {
      // ignore
    }
  }

  if (execution.isCompleted && execution.summary) {
    return (
      <ExecutionSummary
        summary={execution.summary}
        logs={logs}
        onClose={() => {
          execution.clearExecution()
          onComplete()
        }}
      />
    )
  }

  return (
    <div className="rounded-xl border bg-white shadow-sm">
      <div className="flex flex-col gap-4 border-b p-6">
        <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
          <div>
            <h2 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
              <Loader2 className="h-5 w-5 animate-spin text-blue-500" />
              Executing Plan
            </h2>
            <p className="text-sm text-gray-500">{plan.summary}</p>
          </div>
          <div className="flex items-center gap-3">
            {execution.isExecuting && !execution.isAborting && (
              <button
                onClick={execution.abort}
                className="flex items-center gap-2 rounded-lg border border-red-200 px-4 py-2 text-xs font-semibold text-red-600 transition hover:bg-red-50"
              >
                <StopCircle className="h-4 w-4" />
                Abort
              </button>
            )}
            {execution.isAborting && (
              <div className="flex items-center gap-2 text-red-600">
                <Loader2 className="h-4 w-4 animate-spin" />
                Aborting...
              </div>
            )}
          </div>
        </div>

        <div>
          <div className="flex items-center justify-between text-xs text-gray-500">
            <span>Progress</span>
            <span>
              {completedSteps} / {totalSteps}
            </span>
          </div>
          <div className="mt-2 h-2 rounded-full bg-gray-100">
            <div
              className="h-full rounded-full bg-green-500 transition-all duration-300"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>

        {execution.fallbackPolling && (
          <div className="text-xs text-gray-500">
            WebSocket unavailable, falling back to polling every 2s.
          </div>
        )}
      </div>

      {execution.error && (
        <div className="flex items-center gap-2 rounded-b-xl border-t border-red-200 bg-red-50 px-6 py-4 text-xs text-red-700">
          <AlertCircle className="h-4 w-4" />
          {execution.error}
        </div>
      )}

      <div ref={containerRef} className="space-y-3 p-6">
        {execution.steps.map((step) => (
          <ExecutionStep
            key={`execution-step-${step.index}`}
            step={step}
            output={execution.stepOutputs[step.index]}
            isActive={step.status === 'running'}
          />
        ))}
      </div>

      <div className="flex items-center justify-between gap-4 border-t px-6 py-4">
        <button
          onClick={copyLogs}
          className="rounded-lg border border-gray-200 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-gray-600 transition hover:bg-gray-100"
        >
          Copy execution logs
        </button>
        <span className="text-xs text-gray-500">
          Live updates via WebSocket{execution.fallbackPolling ? ' (polling fallback)' : ''}
        </span>
      </div>

      {execution.isFailed && (
        <div className="border-t px-6 py-4">
          <div className="flex items-center justify-between gap-4">
            <div className="text-sm text-red-600">Execution failed.</div>
            <button
              onClick={() => {
                execution.clearExecution()
                onComplete()
              }}
              className="text-xs font-semibold uppercase tracking-wide text-chiffon-primary hover:underline"
            >
              Return to chat
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
