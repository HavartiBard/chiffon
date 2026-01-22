import { useCallback, useEffect, useState } from 'react'
import ApprovalControls from './components/ApprovalControls'
import ChatInterface from './components/ChatInterface'
import ExecutionMonitor from './components/ExecutionMonitor'
import PlanReview from './components/PlanReview'
import { useChat } from './hooks/useChat'
import { usePlanApproval } from './hooks/usePlanApproval'
import type { PlanView } from './types/dashboard'

function App() {
  const chat = useChat()
  const planApproval = usePlanApproval()
  const [executionPlan, setExecutionPlan] = useState<PlanView | null>(null)

  useEffect(() => {
    if (chat.plan) {
      planApproval.setPlan(chat.plan)
    }
  }, [chat.plan, planApproval])

  const sessionId = chat.session?.sessionId || ''
  const activePlan = planApproval.plan

  const handleApprove = useCallback(async () => {
    if (!sessionId || !activePlan) {
      return
    }
    const planToRun = activePlan
    const executionStarted = await planApproval.approve(sessionId)
    if (executionStarted) {
      setExecutionPlan(planToRun)
    }
  }, [activePlan, planApproval, sessionId])

  const handleReject = useCallback(async () => {
    if (!sessionId) {
      return
    }
    await planApproval.reject(sessionId)
  }, [planApproval, sessionId])

  const handleModify = useCallback(
    async (text: string) => {
      if (!sessionId) {
        return
      }
      await planApproval.modify(sessionId, text)
    },
    [planApproval, sessionId]
  )

  const handleExecutionComplete = useCallback(() => {
    planApproval.setPlan(null)
    setExecutionPlan(null)
    chat.clearHistory()
  }, [chat, planApproval])

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="border-b bg-white shadow-sm">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-4">
          <h1 className="text-xl font-semibold text-gray-900">Chiffon Dashboard</h1>
        </div>
      </header>

      <main className="mx-auto grid max-w-6xl gap-6 px-4 py-8 lg:grid-cols-[1.2fr_0.8fr]">
        <ChatInterface />

        <div className="space-y-4">
          {executionPlan ? (
            <ExecutionMonitor plan={executionPlan} sessionId={sessionId} onComplete={handleExecutionComplete} />
          ) : activePlan ? (
            <>
              <PlanReview plan={activePlan} />
              <div className="rounded-xl border bg-white p-6 shadow-sm">
                {planApproval.error && (
                  <div className="mb-3 rounded-lg bg-red-50 px-4 py-2 text-xs text-red-700">
                    {planApproval.error}
                  </div>
                )}
                {planApproval.success && (
                  <div className="mb-3 rounded-lg bg-green-50 px-4 py-2 text-xs text-green-700">
                    {planApproval.success}
                  </div>
                )}
                <ApprovalControls
                  planId={activePlan.planId}
                  sessionId={sessionId}
                  onApprove={handleApprove}
                  onReject={handleReject}
                  onModify={handleModify}
                  isApproving={planApproval.isApproving}
                  isRejecting={planApproval.isRejecting}
                  isModifying={planApproval.isModifying}
                />
              </div>
            </>
          ) : (
            <div className="rounded-xl border bg-white p-6 text-sm text-gray-500 shadow-sm">
              Execute a chat request to generate a plan for review.
            </div>
          )}
        </div>
      </main>
    </div>
  )
}

export default App
