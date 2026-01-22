import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { dashboardApi } from '../api/dashboardClient'
import { useWebSocket } from './useWebSocket'
import type {
  ExecutionSummaryPayload,
  PlanEventPayload,
  PlanStep,
  PlanStatusPayload,
  PlanView,
} from '../types/dashboard'

const POLL_INTERVAL_MS = 2000

interface UseExecutionState {
  plan: PlanView | null
  steps: PlanStep[]
  stepOutputs: Record<number, string[]>
  isExecuting: boolean
  isCompleted: boolean
  isFailed: boolean
  isAborting: boolean
  summary: ExecutionSummaryPayload | null
  error: string | null
  fallbackPolling: boolean
}

interface UseExecutionReturn extends UseExecutionState {
  startExecution: (plan: PlanView) => void
  abort: () => Promise<void>
  clearExecution: () => void
  pollPlanNow: () => Promise<void>
}

function normalizePlanSteps(steps: PlanStep[]): PlanStep[] {
  return steps.map((step) => ({
    ...step,
    status: step.status || 'pending',
  }))
}

export function useExecution(sessionId: string): UseExecutionReturn {
  const [state, setState] = useState<UseExecutionState>({
    plan: null,
    steps: [],
    stepOutputs: {},
    isExecuting: false,
    isCompleted: false,
    isFailed: false,
    isAborting: false,
    summary: null,
    error: null,
    fallbackPolling: false,
  })

  const pollingRef = useRef<NodeJS.Timeout | null>(null)
  const handlePlanEvent = useCallback((payload: PlanEventPayload) => {
    const event = payload.event
    const data = payload.data || {}
    if (event === 'execution_started') {
      setState((prev) => ({ ...prev, isExecuting: true, fallbackPolling: false, error: null }))
    }
    if (event === 'step_completed') {
      const stepIndex = Number(data.step_index)
      const result = data.result as Record<string, unknown>
      setState((prev) => {
        const updatedSteps = [...prev.steps]
        const existing = updatedSteps[stepIndex]
        if (existing) {
          updatedSteps[stepIndex] = {
            ...existing,
            status: (result?.status as PlanStep['status']) ?? existing.status,
            output: (result?.output as string) ?? existing.output,
            error: (result?.error as string) ?? existing.error,
            durationMs: (result?.duration_ms as number) ?? existing.durationMs,
          }
        }
        const outputs = prev.stepOutputs[stepIndex] ?? []
        if (result?.output && typeof result.output === 'string') {
          outputs.push(result.output as string)
        }
        return {
          ...prev,
          steps: updatedSteps,
          stepOutputs: {
            ...prev.stepOutputs,
            [stepIndex]: outputs,
          },
        }
      })
    }
    if (event === 'step_output') {
      const stepIndex = Number(data.step_index)
      const fragment = String(data.output || '')
      if (!fragment) return
      setState((prev) => ({
        ...prev,
        stepOutputs: {
          ...prev.stepOutputs,
          [stepIndex]: [...(prev.stepOutputs[stepIndex] || []), fragment],
        },
      }))
    }
    if (event === 'execution_done' || event === 'plan_completed') {
      const summary = data.summary as ExecutionSummaryPayload
      setState((prev) => ({
        ...prev,
        isExecuting: false,
        isCompleted: true,
        summary: summary ?? prev.summary,
        fallbackPolling: false,
        error: data.error as string | null ?? prev.error,
      }))
    }
    if (event === 'plan_failed') {
      const message = String(data.error || 'Execution failed')
      setState((prev) => ({
        ...prev,
        isExecuting: false,
        isFailed: true,
        error: message,
        fallbackPolling: true,
      }))
    }
  }, [])

  const ws = useWebSocket({
    sessionId,
    onPlanEvent: handlePlanEvent,
    onError: (message) => {
      setState((prev) => ({ ...prev, error: message, fallbackPolling: true }))
    },
  })

  const updateStepsFromStatus = useCallback((status: PlanStatusPayload) => {
    const normalized = normalizePlanSteps(status.steps)
    setState((prev) => ({
      ...prev,
      steps: normalized,
      isExecuting: status.overall_status === 'executing',
      isFailed: status.overall_status === 'failed',
      fallbackPolling: true,
      error: status.overall_status === 'failed' ? 'Execution reported failure' : prev.error,
    }))
  }, [])

  const pollPlanStatus = useCallback(async () => {
    if (!state.plan) {
      return
    }
    const status = await dashboardApi.pollPlan(state.plan.planId)
    updateStepsFromStatus(status)
  }, [state.plan, updateStepsFromStatus])

  useEffect(() => {
    if (!state.plan || !state.isExecuting) {
      return
    }
    if (!ws.isConnected && !pollingRef.current) {
      const poll = async () => {
        try {
          await pollPlanStatus()
        } catch {
          // swallow - fallback will keep retrying
        }
      }
      pollingRef.current = setInterval(poll, POLL_INTERVAL_MS)
      setState((prev) => ({ ...prev, fallbackPolling: true }))
      poll()
    }
    if (ws.isConnected && pollingRef.current) {
      clearInterval(pollingRef.current)
      pollingRef.current = null
      setState((prev) => ({ ...prev, fallbackPolling: false }))
    }
    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current)
        pollingRef.current = null
      }
    }
  }, [state.plan, state.isExecuting, ws.isConnected, pollPlanStatus])

  const pollPlanStatus = useCallback(async () => {
    if (!state.plan) {
      return
    }
    const status = await dashboardApi.pollPlan(state.plan.planId)
    updateStepsFromStatus(status)
  }, [state.plan])

  const updateStepsFromStatus = useCallback((status: PlanStatusPayload) => {
    const normalized = normalizePlanSteps(status.steps)
    setState((prev) => ({
      ...prev,
      steps: normalized,
      isExecuting: status.overall_status === 'executing',
      isFailed: status.overall_status === 'failed',
      fallbackPolling: true,
      error: status.overall_status === 'failed' ? 'Execution reported failure' : prev.error,
    }))
  }, [])

  const startExecution = useCallback(
    (plan: PlanView) => {
    setState({
      plan,
      steps: normalizePlanSteps(plan.steps),
      stepOutputs: {},
      isExecuting: true,
      isCompleted: false,
        isFailed: false,
        isAborting: false,
        summary: null,
        error: null,
        fallbackPolling: false,
      })
      ws.subscribe(plan.planId)
    },
    [ws]
  )

  const abort = useCallback(async () => {
    if (!state.plan || !state.plan.planId) {
      return
    }
    setState((prev) => ({ ...prev, isAborting: true }))
    try {
      await dashboardApi.abortPlan(state.plan.planId, sessionId)
      setState((prev) => ({
        ...prev,
        isExecuting: false,
        isAborting: false,
        error: 'Execution aborted by user',
      }))
    } catch (error) {
      setState((prev) => ({
        ...prev,
        isAborting: false,
        error: 'Failed to abort execution',
      }))
    }
  }, [sessionId, state.plan])

  const clearExecution = useCallback(() => {
    if (state.plan) {
      ws.unsubscribe(state.plan.planId)
    }
    setState({
      plan: null,
      steps: [],
      stepOutputs: {},
      isExecuting: false,
      isCompleted: false,
      isFailed: false,
      isAborting: false,
      summary: null,
      error: null,
      fallbackPolling: false,
    })
    if (pollingRef.current) {
      clearInterval(pollingRef.current)
      pollingRef.current = null
    }
  }, [state.plan, ws])

  return {
    ...state,
    startExecution,
    abort,
    clearExecution,
    pollPlanNow: pollPlanStatus,
  }
}
