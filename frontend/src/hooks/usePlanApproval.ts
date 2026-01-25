import { useCallback, useState } from 'react'
import { dashboardApi } from '../api/dashboardClient'
import type { PlanView } from '../types/dashboard'

interface UsePlanApprovalState {
  plan: PlanView | null
  isApproving: boolean
  isRejecting: boolean
  isModifying: boolean
  error: string | null
  success: string | null
}

interface UsePlanApprovalReturn extends UsePlanApprovalState {
  setPlan: (plan: PlanView | null) => void
  approve: (sessionId: string) => Promise<boolean>
  reject: (sessionId: string) => Promise<boolean>
  modify: (sessionId: string, modification: string) => Promise<boolean>
}

export function usePlanApproval(initialPlan: PlanView | null = null): UsePlanApprovalReturn {
  const [state, setState] = useState<UsePlanApprovalState>({
    plan: initialPlan,
    isApproving: false,
    isRejecting: false,
    isModifying: false,
    error: null,
    success: null,
  })

  const setPlan = useCallback((plan: PlanView | null) => {
    setState((prev) => ({ ...prev, plan, success: null, error: null }))
  }, [])

  const approve = useCallback(async (sessionId: string) => {
    if (!state.plan) return false
    setState((prev) => ({ ...prev, isApproving: true, error: null, success: null }))
    try {
      const result = await dashboardApi.approvePlan(state.plan.planId, sessionId)
      setState((prev) => ({
        ...prev,
        isApproving: false,
        success: result.status === 'approved' ? 'Execution started' : 'Plan approved',
        plan: prev.plan ? { ...prev.plan, status: result.status, canApprove: false } : prev.plan,
      }))
      return Boolean(result.execution_started)
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error'
      setState((prev) => ({ ...prev, isApproving: false, error: `Approval failed: ${message}` }))
      return false
    }
  }, [state.plan])

  const reject = useCallback(async (sessionId: string) => {
    if (!state.plan) return false
    setState((prev) => ({ ...prev, isRejecting: true, error: null, success: null }))
    try {
      const result = await dashboardApi.rejectPlan(state.plan.planId, sessionId)
      setState((prev) => ({
        ...prev,
        isRejecting: false,
        success: result.status === 'rejected' ? 'Plan rejected' : null,
        plan: prev.plan ? { ...prev.plan, status: result.status, canApprove: false } : prev.plan,
      }))
      return true
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error'
      setState((prev) => ({ ...prev, isRejecting: false, error: `Rejection failed: ${message}` }))
      return false
    }
  }, [state.plan])

  const modify = useCallback(async (sessionId: string, modification: string) => {
    if (!state.plan) return false
    setState((prev) => ({ ...prev, isModifying: true, error: null, success: null }))
    try {
      const result = await dashboardApi.modifyPlan(state.plan.planId, sessionId, modification)
      setState((prev) => ({
        ...prev,
        isModifying: false,
        success: 'Plan updated',
        plan: result.new_plan,
      }))
      return true
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error'
      setState((prev) => ({ ...prev, isModifying: false, error: `Modification failed: ${message}` }))
      return false
    }
  }, [state.plan])

  return {
    ...state,
    setPlan,
    approve,
    reject,
    modify,
  }
}
