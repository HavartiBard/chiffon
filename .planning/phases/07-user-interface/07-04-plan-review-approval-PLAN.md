# Phase 7 Plan 04: Plan Review & Approval UI

---
phase: 07-user-interface
plan: 04
type: execute
wave: 2
depends_on: ["07-01", "07-03"]
files_modified:
  - frontend/src/components/PlanReview.tsx
  - frontend/src/components/PlanStep.tsx
  - frontend/src/components/ApprovalControls.tsx
  - frontend/src/components/ModifyDialog.tsx
  - frontend/src/hooks/usePlan.ts
  - frontend/src/App.tsx
  - tests/frontend/PlanReview.test.tsx
autonomous: true
must_haves:
  truths:
    - "Execution plan displayed as step-by-step checklist"
    - "Estimated duration and risk level visible"
    - "Approve button triggers execution"
    - "Reject button cancels plan"
    - "Modify option opens chat for modifications"
    - "Plan readable in under 1 minute"
  artifacts:
    - path: "frontend/src/components/PlanReview.tsx"
      provides: "Plan display component"
    - path: "frontend/src/components/ApprovalControls.tsx"
      provides: "Approve/reject/modify buttons"
    - path: "frontend/src/hooks/usePlan.ts"
      provides: "Plan state management"
  key_links:
    - from: "frontend/src/components/PlanReview.tsx"
      to: "frontend/src/hooks/usePlan.ts"
      via: "hook consumption"
      pattern: "usePlan"
    - from: "frontend/src/components/ApprovalControls.tsx"
      to: "frontend/src/api/dashboard.ts"
      via: "API calls"
      pattern: "dashboardApi\\.approvePlan"
---

<objective>
Create the plan review and approval UI components. When the orchestrator returns a plan, users see a clear step-by-step breakdown with duration estimates, risk level, and approve/reject/modify controls.

Purpose: This satisfies UI-02 (orchestrator presents plan for approval) and UI-03 (user can approve, reject, or modify). The plan must be scannable in under 1 minute.

Output: PlanReview component with step checklist, ApprovalControls with three-option workflow, and ModifyDialog for chat-based modifications.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@frontend/src/types/index.ts
@frontend/src/api/dashboard.ts
@frontend/src/components/Chat.tsx
</context>

<tasks>

<task type="auto">
  <name>Task 1: Create usePlan hook for plan state management</name>
  <files>
    frontend/src/hooks/usePlan.ts
  </files>
  <action>
Create a React hook for managing plan state and operations:

1. Create frontend/src/hooks/usePlan.ts:
   ```typescript
   import { useState, useCallback } from 'react'
   import { dashboardApi } from '../api/dashboard'
   import type { DashboardPlan, ApiError } from '../types'

   interface UsePlanState {
     plan: DashboardPlan | null
     isLoading: boolean
     isApproving: boolean
     isRejecting: boolean
     isModifying: boolean
     error: string | null
   }

   interface UsePlanReturn extends UsePlanState {
     loadPlan: (planId: string) => Promise<void>
     approvePlan: () => Promise<boolean>
     rejectPlan: () => Promise<boolean>
     modifyPlan: (sessionId: string, modification: string) => Promise<DashboardPlan | null>
     clearError: () => void
     setPlan: (plan: DashboardPlan | null) => void
   }

   export function usePlan(initialPlan: DashboardPlan | null = null): UsePlanReturn {
     const [state, setState] = useState<UsePlanState>({
       plan: initialPlan,
       isLoading: false,
       isApproving: false,
       isRejecting: false,
       isModifying: false,
       error: null,
     })

     const loadPlan = useCallback(async (planId: string) => {
       setState(prev => ({ ...prev, isLoading: true, error: null }))

       try {
         const plan = await dashboardApi.getPlan(planId)
         setState(prev => ({ ...prev, plan, isLoading: false }))
       } catch (err) {
         const apiError = err as ApiError
         setState(prev => ({
           ...prev,
           isLoading: false,
           error: `Failed to load plan: ${apiError.detail}`,
         }))
       }
     }, [])

     const approvePlan = useCallback(async (): Promise<boolean> => {
       if (!state.plan) return false

       setState(prev => ({ ...prev, isApproving: true, error: null }))

       try {
         const result = await dashboardApi.approvePlan(state.plan.plan_id)
         setState(prev => ({
           ...prev,
           plan: prev.plan ? { ...prev.plan, status: 'approved', can_approve: false } : null,
           isApproving: false,
         }))
         return result.execution_started
       } catch (err) {
         const apiError = err as ApiError
         setState(prev => ({
           ...prev,
           isApproving: false,
           error: `Approval failed: ${apiError.detail}`,
         }))
         return false
       }
     }, [state.plan])

     const rejectPlan = useCallback(async (): Promise<boolean> => {
       if (!state.plan) return false

       setState(prev => ({ ...prev, isRejecting: true, error: null }))

       try {
         await dashboardApi.rejectPlan(state.plan.plan_id)
         setState(prev => ({
           ...prev,
           plan: prev.plan ? { ...prev.plan, status: 'rejected', can_approve: false } : null,
           isRejecting: false,
         }))
         return true
       } catch (err) {
         const apiError = err as ApiError
         setState(prev => ({
           ...prev,
           isRejecting: false,
           error: `Rejection failed: ${apiError.detail}`,
         }))
         return false
       }
     }, [state.plan])

     const modifyPlan = useCallback(async (
       sessionId: string,
       modification: string
     ): Promise<DashboardPlan | null> => {
       if (!state.plan) return null

       setState(prev => ({ ...prev, isModifying: true, error: null }))

       try {
         const result = await dashboardApi.modifyPlan(
           state.plan.plan_id,
           sessionId,
           modification
         )
         setState(prev => ({
           ...prev,
           plan: result.new_plan,
           isModifying: false,
         }))
         return result.new_plan
       } catch (err) {
         const apiError = err as ApiError
         setState(prev => ({
           ...prev,
           isModifying: false,
           error: `Modification failed: ${apiError.detail}`,
         }))
         return null
       }
     }, [state.plan])

     const clearError = useCallback(() => {
       setState(prev => ({ ...prev, error: null }))
     }, [])

     const setPlan = useCallback((plan: DashboardPlan | null) => {
       setState(prev => ({ ...prev, plan }))
     }, [])

     return {
       ...state,
       loadPlan,
       approvePlan,
       rejectPlan,
       modifyPlan,
       clearError,
       setPlan,
     }
   }
   ```
  </action>
  <verify>
    - [ ] usePlan hook compiles without errors
    - [ ] All state transitions work (loading, approving, rejecting, modifying)
    - [ ] Error handling captures API failures
    - [ ] Import works: `import { usePlan } from './hooks/usePlan'`
  </verify>
  <done>usePlan hook created with full state management</done>
</task>

<task type="auto">
  <name>Task 2: Create PlanReview and PlanStep components</name>
  <files>
    frontend/src/components/PlanStep.tsx
    frontend/src/components/PlanReview.tsx
  </files>
  <action>
Create components for displaying the execution plan:

1. Create frontend/src/components/PlanStep.tsx:
   ```typescript
   import { clsx } from 'clsx'
   import { CheckCircle, Circle, Loader2, XCircle, MinusCircle } from 'lucide-react'
   import type { PlanStep as PlanStepType } from '../types'

   interface PlanStepProps {
     step: PlanStepType
     isExpanded?: boolean
     onToggle?: () => void
   }

   const statusIcons = {
     pending: Circle,
     running: Loader2,
     completed: CheckCircle,
     failed: XCircle,
     skipped: MinusCircle,
   }

   const statusColors = {
     pending: 'text-gray-400',
     running: 'text-blue-500',
     completed: 'text-green-500',
     failed: 'text-red-500',
     skipped: 'text-gray-400',
   }

   export default function PlanStep({ step, isExpanded, onToggle }: PlanStepProps) {
     const Icon = statusIcons[step.status]
     const colorClass = statusColors[step.status]

     return (
       <div
         className={clsx(
           'border rounded-lg p-4 transition-all',
           step.status === 'running' && 'border-blue-300 bg-blue-50',
           step.status === 'completed' && 'border-green-200 bg-green-50',
           step.status === 'failed' && 'border-red-200 bg-red-50',
           step.status === 'pending' && 'border-gray-200 bg-white'
         )}
       >
         <div
           className="flex items-start gap-3 cursor-pointer"
           onClick={onToggle}
         >
           <div className={clsx('flex-shrink-0 mt-0.5', colorClass)}>
             <Icon
               className={clsx(
                 'w-5 h-5',
                 step.status === 'running' && 'animate-spin'
               )}
             />
           </div>

           <div className="flex-1 min-w-0">
             <div className="flex items-center gap-2">
               <span className="text-sm text-gray-500">Step {step.index + 1}</span>
               {step.duration_ms && (
                 <span className="text-xs text-gray-400">
                   ({(step.duration_ms / 1000).toFixed(1)}s)
                 </span>
               )}
             </div>
             <h4 className="font-medium text-gray-900">{step.name}</h4>
             <p className="text-sm text-gray-600 mt-1">{step.description}</p>
           </div>
         </div>

         {/* Expanded content */}
         {isExpanded && (step.output || step.error) && (
           <div className="mt-4 pl-8 border-t pt-4">
             {step.output && (
               <pre className="text-xs bg-gray-900 text-gray-100 p-3 rounded overflow-x-auto">
                 {step.output}
               </pre>
             )}
             {step.error && (
               <div className="text-sm text-red-600 bg-red-50 p-3 rounded">
                 {step.error}
               </div>
             )}
           </div>
         )}
       </div>
     )
   }
   ```

2. Create frontend/src/components/PlanReview.tsx:
   ```typescript
   import { useState } from 'react'
   import { clsx } from 'clsx'
   import { Clock, AlertTriangle, Shield, ChevronDown, ChevronUp } from 'lucide-react'
   import type { DashboardPlan } from '../types'
   import PlanStep from './PlanStep'
   import ApprovalControls from './ApprovalControls'

   interface PlanReviewProps {
     plan: DashboardPlan
     sessionId: string
     onApprove: () => Promise<boolean>
     onReject: () => Promise<boolean>
     onModify: (modification: string) => Promise<void>
     isApproving?: boolean
     isRejecting?: boolean
     isModifying?: boolean
   }

   const riskColors = {
     low: 'text-green-600 bg-green-100',
     medium: 'text-yellow-600 bg-yellow-100',
     high: 'text-red-600 bg-red-100',
   }

   const riskIcons = {
     low: Shield,
     medium: AlertTriangle,
     high: AlertTriangle,
   }

   export default function PlanReview({
     plan,
     sessionId,
     onApprove,
     onReject,
     onModify,
     isApproving = false,
     isRejecting = false,
     isModifying = false,
   }: PlanReviewProps) {
     const [expandedStep, setExpandedStep] = useState<number | null>(null)
     const [showAllSteps, setShowAllSteps] = useState(false)

     const RiskIcon = riskIcons[plan.risk_level]
     const visibleSteps = showAllSteps ? plan.steps : plan.steps.slice(0, 5)
     const hasMoreSteps = plan.steps.length > 5

     return (
       <div className="bg-white rounded-xl border shadow-sm overflow-hidden">
         {/* Header */}
         <div className="p-6 border-b bg-gray-50">
           <h2 className="text-xl font-semibold text-gray-900">Execution Plan</h2>
           <p className="text-gray-600 mt-2">{plan.summary}</p>

           {/* Meta info */}
           <div className="flex flex-wrap gap-4 mt-4">
             <div className="flex items-center gap-2 text-sm text-gray-600">
               <Clock className="w-4 h-4" />
               <span>{plan.estimated_duration}</span>
             </div>

             <div
               className={clsx(
                 'flex items-center gap-2 text-sm px-2 py-1 rounded-full',
                 riskColors[plan.risk_level]
               )}
             >
               <RiskIcon className="w-4 h-4" />
               <span className="capitalize">{plan.risk_level} Risk</span>
             </div>

             <div className="text-sm text-gray-500">
               {plan.steps.length} steps
             </div>
           </div>
         </div>

         {/* Steps */}
         <div className="p-6">
           <h3 className="font-medium text-gray-900 mb-4">Execution Steps</h3>

           <div className="space-y-3">
             {visibleSteps.map((step, index) => (
               <PlanStep
                 key={step.index}
                 step={step}
                 isExpanded={expandedStep === index}
                 onToggle={() =>
                   setExpandedStep(expandedStep === index ? null : index)
                 }
               />
             ))}
           </div>

           {hasMoreSteps && (
             <button
               onClick={() => setShowAllSteps(!showAllSteps)}
               className="flex items-center gap-1 text-sm text-chiffon-primary mt-4 hover:underline"
             >
               {showAllSteps ? (
                 <>
                   <ChevronUp className="w-4 h-4" />
                   Show less
                 </>
               ) : (
                 <>
                   <ChevronDown className="w-4 h-4" />
                   Show {plan.steps.length - 5} more steps
                 </>
               )}
             </button>
           )}
         </div>

         {/* Resource requirements */}
         {Object.keys(plan.resource_requirements).length > 0 && (
           <div className="px-6 pb-6">
             <h3 className="font-medium text-gray-900 mb-2">
               Resource Requirements
             </h3>
             <div className="bg-gray-50 rounded-lg p-4 text-sm">
               <dl className="grid grid-cols-2 gap-2">
                 {Object.entries(plan.resource_requirements).map(([key, value]) => (
                   <div key={key}>
                     <dt className="text-gray-500">{key}</dt>
                     <dd className="text-gray-900">{String(value)}</dd>
                   </div>
                 ))}
               </dl>
             </div>
           </div>
         )}

         {/* Approval controls */}
         {plan.can_approve && (
           <div className="p-6 border-t bg-gray-50">
             <ApprovalControls
               onApprove={onApprove}
               onReject={onReject}
               onModify={onModify}
               isApproving={isApproving}
               isRejecting={isRejecting}
               isModifying={isModifying}
               canModify={plan.can_modify}
             />
           </div>
         )}

         {/* Status indicator for non-pending plans */}
         {!plan.can_approve && (
           <div
             className={clsx(
               'p-4 border-t text-center text-sm font-medium',
               plan.status === 'approved' && 'bg-green-50 text-green-700',
               plan.status === 'rejected' && 'bg-red-50 text-red-700',
               plan.status === 'executing' && 'bg-blue-50 text-blue-700',
               plan.status === 'completed' && 'bg-green-50 text-green-700'
             )}
           >
             Status: {plan.status.charAt(0).toUpperCase() + plan.status.slice(1)}
           </div>
         )}
       </div>
     )
   }
   ```
  </action>
  <verify>
    - [ ] PlanStep renders with correct status icons
    - [ ] PlanReview displays summary, duration, risk level
    - [ ] Steps can be expanded to show output/error
    - [ ] Show more/less works for plans with >5 steps
  </verify>
  <done>PlanReview and PlanStep components created with full plan display</done>
</task>

<task type="auto">
  <name>Task 3: Create ApprovalControls and ModifyDialog components</name>
  <files>
    frontend/src/components/ApprovalControls.tsx
    frontend/src/components/ModifyDialog.tsx
    frontend/src/App.tsx
    tests/frontend/PlanReview.test.tsx
  </files>
  <action>
Create the approval workflow components and tests:

1. Create frontend/src/components/ApprovalControls.tsx:
   ```typescript
   import { useState } from 'react'
   import { clsx } from 'clsx'
   import { Check, X, Edit2, Loader2 } from 'lucide-react'
   import ModifyDialog from './ModifyDialog'

   interface ApprovalControlsProps {
     onApprove: () => Promise<boolean>
     onReject: () => Promise<boolean>
     onModify: (modification: string) => Promise<void>
     isApproving?: boolean
     isRejecting?: boolean
     isModifying?: boolean
     canModify?: boolean
   }

   export default function ApprovalControls({
     onApprove,
     onReject,
     onModify,
     isApproving = false,
     isRejecting = false,
     isModifying = false,
     canModify = true,
   }: ApprovalControlsProps) {
     const [showModifyDialog, setShowModifyDialog] = useState(false)
     const isDisabled = isApproving || isRejecting || isModifying

     const handleApprove = async () => {
       if (window.confirm('Are you sure you want to approve this plan and start execution?')) {
         await onApprove()
       }
     }

     const handleReject = async () => {
       if (window.confirm('Are you sure you want to reject this plan?')) {
         await onReject()
       }
     }

     const handleModifySubmit = async (modification: string) => {
       await onModify(modification)
       setShowModifyDialog(false)
     }

     return (
       <>
         <div className="flex flex-col sm:flex-row gap-3">
           {/* Approve button */}
           <button
             onClick={handleApprove}
             disabled={isDisabled}
             className={clsx(
               'flex-1 flex items-center justify-center gap-2 px-6 py-3 rounded-lg font-medium transition-colors',
               isDisabled
                 ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
                 : 'bg-green-600 text-white hover:bg-green-700'
             )}
           >
             {isApproving ? (
               <Loader2 className="w-5 h-5 animate-spin" />
             ) : (
               <Check className="w-5 h-5" />
             )}
             {isApproving ? 'Approving...' : 'Approve & Execute'}
           </button>

           {/* Reject button */}
           <button
             onClick={handleReject}
             disabled={isDisabled}
             className={clsx(
               'flex-1 flex items-center justify-center gap-2 px-6 py-3 rounded-lg font-medium transition-colors',
               isDisabled
                 ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
                 : 'bg-red-100 text-red-700 hover:bg-red-200'
             )}
           >
             {isRejecting ? (
               <Loader2 className="w-5 h-5 animate-spin" />
             ) : (
               <X className="w-5 h-5" />
             )}
             {isRejecting ? 'Rejecting...' : 'Reject'}
           </button>

           {/* Modify button */}
           {canModify && (
             <button
               onClick={() => setShowModifyDialog(true)}
               disabled={isDisabled}
               className={clsx(
                 'flex-1 flex items-center justify-center gap-2 px-6 py-3 rounded-lg font-medium transition-colors',
                 isDisabled
                   ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
                   : 'bg-chiffon-primary/10 text-chiffon-primary hover:bg-chiffon-primary/20'
               )}
             >
               {isModifying ? (
                 <Loader2 className="w-5 h-5 animate-spin" />
               ) : (
                 <Edit2 className="w-5 h-5" />
               )}
               {isModifying ? 'Modifying...' : 'Request Changes'}
             </button>
           )}
         </div>

         {/* Modify dialog */}
         <ModifyDialog
           isOpen={showModifyDialog}
           onClose={() => setShowModifyDialog(false)}
           onSubmit={handleModifySubmit}
           isLoading={isModifying}
         />
       </>
     )
   }
   ```

2. Create frontend/src/components/ModifyDialog.tsx:
   ```typescript
   import { useState, useEffect, useRef } from 'react'
   import { clsx } from 'clsx'
   import { X, Send, Loader2 } from 'lucide-react'

   interface ModifyDialogProps {
     isOpen: boolean
     onClose: () => void
     onSubmit: (modification: string) => Promise<void>
     isLoading?: boolean
   }

   export default function ModifyDialog({
     isOpen,
     onClose,
     onSubmit,
     isLoading = false,
   }: ModifyDialogProps) {
     const [input, setInput] = useState('')
     const textareaRef = useRef<HTMLTextAreaElement>(null)

     // Focus textarea when dialog opens
     useEffect(() => {
       if (isOpen && textareaRef.current) {
         textareaRef.current.focus()
       }
     }, [isOpen])

     // Reset input when dialog closes
     useEffect(() => {
       if (!isOpen) {
         setInput('')
       }
     }, [isOpen])

     const handleSubmit = async () => {
       if (input.trim() && !isLoading) {
         await onSubmit(input.trim())
       }
     }

     if (!isOpen) return null

     return (
       <div className="fixed inset-0 z-50 flex items-center justify-center">
         {/* Backdrop */}
         <div
           className="absolute inset-0 bg-black/50"
           onClick={onClose}
         />

         {/* Dialog */}
         <div className="relative bg-white rounded-xl shadow-xl max-w-lg w-full mx-4 overflow-hidden">
           {/* Header */}
           <div className="flex items-center justify-between p-4 border-b">
             <h3 className="text-lg font-semibold">Request Plan Changes</h3>
             <button
               onClick={onClose}
               className="p-1 rounded-lg hover:bg-gray-100"
             >
               <X className="w-5 h-5" />
             </button>
           </div>

           {/* Content */}
           <div className="p-4">
             <p className="text-sm text-gray-600 mb-4">
               Describe the changes you'd like to make to this plan. For example:
             </p>
             <ul className="text-sm text-gray-500 mb-4 list-disc list-inside">
               <li>"Use staging environment first"</li>
               <li>"Add a backup step before deployment"</li>
               <li>"Skip the DNS configuration step"</li>
             </ul>

             <textarea
               ref={textareaRef}
               value={input}
               onChange={(e) => setInput(e.target.value)}
               placeholder="Describe your requested changes..."
               disabled={isLoading}
               rows={4}
               className={clsx(
                 'w-full border rounded-lg p-3 resize-none',
                 'focus:ring-2 focus:ring-chiffon-primary focus:border-transparent',
                 isLoading && 'opacity-50'
               )}
             />
           </div>

           {/* Footer */}
           <div className="flex justify-end gap-3 p-4 border-t bg-gray-50">
             <button
               onClick={onClose}
               disabled={isLoading}
               className="px-4 py-2 rounded-lg text-gray-700 hover:bg-gray-100"
             >
               Cancel
             </button>
             <button
               onClick={handleSubmit}
               disabled={!input.trim() || isLoading}
               className={clsx(
                 'flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition-colors',
                 input.trim() && !isLoading
                   ? 'bg-chiffon-primary text-white hover:bg-chiffon-secondary'
                   : 'bg-gray-100 text-gray-400 cursor-not-allowed'
               )}
             >
               {isLoading ? (
                 <Loader2 className="w-4 h-4 animate-spin" />
               ) : (
                 <Send className="w-4 h-4" />
               )}
               {isLoading ? 'Updating...' : 'Submit Changes'}
             </button>
           </div>
         </div>
       </div>
     )
   }
   ```

3. Update frontend/src/App.tsx to integrate PlanReview:
   ```typescript
   import { useState } from 'react'
   import Chat from './components/Chat'
   import PlanReview from './components/PlanReview'
   import { useChat } from './hooks/useChat'
   import { usePlan } from './hooks/usePlan'

   function App() {
     const chat = useChat()
     const plan = usePlan(chat.currentPlan)
     const [view, setView] = useState<'chat' | 'plan'>('chat')

     // Switch to plan view when plan is ready
     const handlePlanReady = () => {
       if (chat.currentPlan) {
         plan.setPlan(chat.currentPlan)
         setView('plan')
       }
     }

     const handleModify = async (modification: string) => {
       if (!chat.session) return
       await plan.modifyPlan(chat.session.session_id, modification)
     }

     return (
       <div className="min-h-screen bg-gray-50">
         <header className="bg-white shadow-sm border-b">
           <div className="max-w-4xl mx-auto px-4 py-4 flex items-center justify-between">
             <h1 className="text-xl font-semibold text-gray-900">
               Chiffon Dashboard
             </h1>
             {plan.plan && (
               <div className="flex gap-2">
                 <button
                   onClick={() => setView('chat')}
                   className={`px-3 py-1 rounded-lg text-sm ${
                     view === 'chat' ? 'bg-chiffon-primary text-white' : 'bg-gray-100'
                   }`}
                 >
                   Chat
                 </button>
                 <button
                   onClick={() => setView('plan')}
                   className={`px-3 py-1 rounded-lg text-sm ${
                     view === 'plan' ? 'bg-chiffon-primary text-white' : 'bg-gray-100'
                   }`}
                 >
                   Plan
                 </button>
               </div>
             )}
           </div>
         </header>

         <main className="max-w-4xl mx-auto px-4 py-8">
           {view === 'chat' ? (
             <Chat onPlanReady={handlePlanReady} />
           ) : plan.plan ? (
             <PlanReview
               plan={plan.plan}
               sessionId={chat.session?.session_id || ''}
               onApprove={plan.approvePlan}
               onReject={plan.rejectPlan}
               onModify={handleModify}
               isApproving={plan.isApproving}
               isRejecting={plan.isRejecting}
               isModifying={plan.isModifying}
             />
           ) : (
             <div className="text-center text-gray-500 py-12">
               No plan available. Start a conversation to create one.
             </div>
           )}
         </main>
       </div>
     )
   }

   export default App
   ```

4. Create tests/frontend/PlanReview.test.tsx:
   ```typescript
   import { describe, it, expect, vi, beforeEach } from 'vitest'
   import { render, screen, fireEvent, waitFor } from '@testing-library/react'
   import PlanReview from '../../src/components/PlanReview'
   import type { DashboardPlan } from '../../src/types'

   const mockPlan: DashboardPlan = {
     plan_id: 'test-plan-1',
     request_id: 'test-request-1',
     summary: 'Deploy Kuma monitoring to homelab',
     steps: [
       { index: 0, name: 'Check prerequisites', description: 'Verify Docker is running', status: 'pending' },
       { index: 1, name: 'Pull container image', description: 'Pull kuma image from registry', status: 'pending' },
       { index: 2, name: 'Create configuration', description: 'Generate kuma config file', status: 'pending' },
     ],
     estimated_duration: '~5 minutes',
     risk_level: 'low',
     resource_requirements: { cpu: '2 cores', memory: '512MB' },
     status: 'pending_approval',
     can_approve: true,
     can_modify: true,
     can_abort: false,
   }

   describe('PlanReview', () => {
     const mockOnApprove = vi.fn()
     const mockOnReject = vi.fn()
     const mockOnModify = vi.fn()

     beforeEach(() => {
       vi.resetAllMocks()
       mockOnApprove.mockResolvedValue(true)
       mockOnReject.mockResolvedValue(true)
     })

     it('renders plan summary', () => {
       render(
         <PlanReview
           plan={mockPlan}
           sessionId="test-session"
           onApprove={mockOnApprove}
           onReject={mockOnReject}
           onModify={mockOnModify}
         />
       )

       expect(screen.getByText('Deploy Kuma monitoring to homelab')).toBeInTheDocument()
       expect(screen.getByText('~5 minutes')).toBeInTheDocument()
       expect(screen.getByText('Low Risk')).toBeInTheDocument()
     })

     it('renders all steps', () => {
       render(
         <PlanReview
           plan={mockPlan}
           sessionId="test-session"
           onApprove={mockOnApprove}
           onReject={mockOnReject}
           onModify={mockOnModify}
         />
       )

       expect(screen.getByText('Check prerequisites')).toBeInTheDocument()
       expect(screen.getByText('Pull container image')).toBeInTheDocument()
       expect(screen.getByText('Create configuration')).toBeInTheDocument()
     })

     it('calls onApprove when approve button clicked', async () => {
       window.confirm = vi.fn().mockReturnValue(true)

       render(
         <PlanReview
           plan={mockPlan}
           sessionId="test-session"
           onApprove={mockOnApprove}
           onReject={mockOnReject}
           onModify={mockOnModify}
         />
       )

       fireEvent.click(screen.getByText('Approve & Execute'))

       await waitFor(() => {
         expect(mockOnApprove).toHaveBeenCalled()
       })
     })

     it('calls onReject when reject button clicked', async () => {
       window.confirm = vi.fn().mockReturnValue(true)

       render(
         <PlanReview
           plan={mockPlan}
           sessionId="test-session"
           onApprove={mockOnApprove}
           onReject={mockOnReject}
           onModify={mockOnModify}
         />
       )

       fireEvent.click(screen.getByText('Reject'))

       await waitFor(() => {
         expect(mockOnReject).toHaveBeenCalled()
       })
     })

     it('opens modify dialog when request changes clicked', () => {
       render(
         <PlanReview
           plan={mockPlan}
           sessionId="test-session"
           onApprove={mockOnApprove}
           onReject={mockOnReject}
           onModify={mockOnModify}
         />
       )

       fireEvent.click(screen.getByText('Request Changes'))

       expect(screen.getByText('Request Plan Changes')).toBeInTheDocument()
     })

     it('hides approval controls when plan not approvable', () => {
       const approvedPlan = { ...mockPlan, can_approve: false, status: 'approved' }

       render(
         <PlanReview
           plan={approvedPlan}
           sessionId="test-session"
           onApprove={mockOnApprove}
           onReject={mockOnReject}
           onModify={mockOnModify}
         />
       )

       expect(screen.queryByText('Approve & Execute')).not.toBeInTheDocument()
       expect(screen.getByText('Status: Approved')).toBeInTheDocument()
     })
   })
   ```
  </action>
  <verify>
    - [ ] ApprovalControls renders three buttons (approve, reject, modify)
    - [ ] Approve button calls onApprove after confirmation
    - [ ] Reject button calls onReject after confirmation
    - [ ] Modify button opens ModifyDialog
    - [ ] ModifyDialog accepts text input and submits
    - [ ] All tests pass: `cd frontend && npm test`
  </verify>
  <done>ApprovalControls and ModifyDialog created with full workflow support</done>
</task>

</tasks>

<verification>
After all tasks complete:
1. Start frontend: `cd frontend && npm run dev`
2. Verify plan review renders with mock data
3. Test approve/reject/modify buttons (will fail without backend)
4. Run tests: `npm test`
</verification>

<success_criteria>
- Plan displays summary, steps, duration, risk level
- Steps show as checklist with status icons
- Approve triggers execution (with confirmation)
- Reject cancels plan (with confirmation)
- Modify opens dialog for chat-based changes
- Plan readable in <1 minute (summary + 5 visible steps)
- All tests pass (target: 15+ test cases)
</success_criteria>

<output>
After completion, create `.planning/phases/07-user-interface/07-04-SUMMARY.md`
</output>
