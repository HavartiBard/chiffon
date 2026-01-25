# Phase 7 Plan 05: Execution Monitoring UI

---
phase: 07-user-interface
plan: 05
type: execute
wave: 3
depends_on: ["07-02", "07-04"]
files_modified:
  - frontend/src/components/ExecutionMonitor.tsx
  - frontend/src/components/ExecutionStep.tsx
  - frontend/src/components/ExecutionSummary.tsx
  - frontend/src/hooks/useExecution.ts
  - frontend/src/hooks/useWebSocket.ts
  - frontend/src/App.tsx
  - tests/frontend/ExecutionMonitor.test.tsx
autonomous: true
must_haves:
  truths:
    - "Real-time step status updates visible during execution"
    - "Step output expandable to show ansible output"
    - "Abort button available during execution"
    - "Post-execution summary shows all results"
    - "Audit trail link visible in summary"
  artifacts:
    - path: "frontend/src/components/ExecutionMonitor.tsx"
      provides: "Real-time execution display"
    - path: "frontend/src/hooks/useWebSocket.ts"
      provides: "WebSocket connection hook"
    - path: "frontend/src/components/ExecutionSummary.tsx"
      provides: "Post-execution summary"
  key_links:
    - from: "frontend/src/hooks/useWebSocket.ts"
      to: "src/dashboard/websocket.py"
      via: "WebSocket connection"
      pattern: "new WebSocket"
    - from: "frontend/src/components/ExecutionMonitor.tsx"
      to: "frontend/src/hooks/useExecution.ts"
      via: "hook consumption"
      pattern: "useExecution"
---

<objective>
Create the execution monitoring UI with real-time WebSocket updates. Users see step-by-step progress during execution, can view ansible output, abort if needed, and review a complete summary after execution.

Purpose: This satisfies UI-04 (execution log shows all steps, outputs, and decisions). Real-time visibility builds user confidence and enables quick intervention if something goes wrong.

Output: ExecutionMonitor with WebSocket-driven updates, abort functionality, and post-execution summary with audit trail link.
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
@frontend/src/components/PlanReview.tsx
@src/dashboard/websocket.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Create useWebSocket hook for real-time updates</name>
  <files>
    frontend/src/hooks/useWebSocket.ts
    frontend/src/types/index.ts
  </files>
  <action>
Create a WebSocket connection hook for real-time execution updates:

1. Add WebSocket message types to frontend/src/types/index.ts:
   ```typescript
   // WebSocket message types
   export type WSMessageType =
     | 'subscribed'
     | 'unsubscribed'
     | 'step_status'
     | 'step_output'
     | 'plan_completed'
     | 'plan_failed'
     | 'pong'
     | 'error'

   export interface WSMessage {
     type: WSMessageType
     plan_id?: string
     timestamp?: string
     [key: string]: unknown
   }

   export interface WSStepStatus extends WSMessage {
     type: 'step_status'
     step_index: number
     step_name: string
     status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped'
     output?: string
     error?: string
   }

   export interface WSStepOutput extends WSMessage {
     type: 'step_output'
     step_index: number
     output: string
   }

   export interface WSPlanCompleted extends WSMessage {
     type: 'plan_completed'
     summary: {
       total_duration_ms: number
       steps_completed: number
       steps_failed: number
       resources_used: Record<string, unknown>
       audit_trail_url?: string
     }
   }

   export interface WSPlanFailed extends WSMessage {
     type: 'plan_failed'
     error: string
     failed_step_index?: number
   }
   ```

2. Create frontend/src/hooks/useWebSocket.ts:
   ```typescript
   import { useState, useEffect, useCallback, useRef } from 'react'
   import type { WSMessage, WSStepStatus, WSStepOutput, WSPlanCompleted, WSPlanFailed } from '../types'

   interface UseWebSocketOptions {
     sessionId: string
     onStepStatus?: (message: WSStepStatus) => void
     onStepOutput?: (message: WSStepOutput) => void
     onPlanCompleted?: (message: WSPlanCompleted) => void
     onPlanFailed?: (message: WSPlanFailed) => void
     onError?: (error: string) => void
   }

   interface UseWebSocketReturn {
     isConnected: boolean
     isConnecting: boolean
     error: string | null
     subscribe: (planId: string) => void
     unsubscribe: (planId: string) => void
     reconnect: () => void
   }

   export function useWebSocket({
     sessionId,
     onStepStatus,
     onStepOutput,
     onPlanCompleted,
     onPlanFailed,
     onError,
   }: UseWebSocketOptions): UseWebSocketReturn {
     const [isConnected, setIsConnected] = useState(false)
     const [isConnecting, setIsConnecting] = useState(false)
     const [error, setError] = useState<string | null>(null)
     const wsRef = useRef<WebSocket | null>(null)
     const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null)
     const pingIntervalRef = useRef<NodeJS.Timeout | null>(null)

     const connect = useCallback(() => {
       if (wsRef.current?.readyState === WebSocket.OPEN) return

       setIsConnecting(true)
       setError(null)

       const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
       const wsUrl = `${protocol}//${window.location.host}/ws/${sessionId}`

       const ws = new WebSocket(wsUrl)
       wsRef.current = ws

       ws.onopen = () => {
         setIsConnected(true)
         setIsConnecting(false)
         setError(null)

         // Start ping interval
         pingIntervalRef.current = setInterval(() => {
           if (ws.readyState === WebSocket.OPEN) {
             ws.send(JSON.stringify({ type: 'ping' }))
           }
         }, 30000)
       }

       ws.onclose = () => {
         setIsConnected(false)
         setIsConnecting(false)

         // Clear ping interval
         if (pingIntervalRef.current) {
           clearInterval(pingIntervalRef.current)
         }

         // Attempt reconnect after 3 seconds
         reconnectTimeoutRef.current = setTimeout(() => {
           connect()
         }, 3000)
       }

       ws.onerror = (event) => {
         setError('WebSocket connection error')
         onError?.('WebSocket connection error')
       }

       ws.onmessage = (event) => {
         try {
           const message = JSON.parse(event.data) as WSMessage

           switch (message.type) {
             case 'step_status':
               onStepStatus?.(message as WSStepStatus)
               break
             case 'step_output':
               onStepOutput?.(message as WSStepOutput)
               break
             case 'plan_completed':
               onPlanCompleted?.(message as WSPlanCompleted)
               break
             case 'plan_failed':
               onPlanFailed?.(message as WSPlanFailed)
               break
             case 'error':
               setError(message.message as string)
               onError?.(message.message as string)
               break
           }
         } catch (err) {
           console.error('Failed to parse WebSocket message:', err)
         }
       }
     }, [sessionId, onStepStatus, onStepOutput, onPlanCompleted, onPlanFailed, onError])

     const disconnect = useCallback(() => {
       if (reconnectTimeoutRef.current) {
         clearTimeout(reconnectTimeoutRef.current)
       }
       if (pingIntervalRef.current) {
         clearInterval(pingIntervalRef.current)
       }
       if (wsRef.current) {
         wsRef.current.close()
         wsRef.current = null
       }
     }, [])

     const subscribe = useCallback((planId: string) => {
       if (wsRef.current?.readyState === WebSocket.OPEN) {
         wsRef.current.send(JSON.stringify({ type: 'subscribe', plan_id: planId }))
       }
     }, [])

     const unsubscribe = useCallback((planId: string) => {
       if (wsRef.current?.readyState === WebSocket.OPEN) {
         wsRef.current.send(JSON.stringify({ type: 'unsubscribe', plan_id: planId }))
       }
     }, [])

     const reconnect = useCallback(() => {
       disconnect()
       connect()
     }, [connect, disconnect])

     // Connect on mount
     useEffect(() => {
       connect()
       return () => disconnect()
     }, [connect, disconnect])

     return {
       isConnected,
       isConnecting,
       error,
       subscribe,
       unsubscribe,
       reconnect,
     }
   }
   ```
  </action>
  <verify>
    - [ ] useWebSocket connects to /ws/{sessionId}
    - [ ] Subscribe/unsubscribe messages sent correctly
    - [ ] Message handlers called for each message type
    - [ ] Reconnection logic works on disconnect
    - [ ] Ping/pong keepalive active
  </verify>
  <done>useWebSocket hook created with full WebSocket lifecycle management</done>
</task>

<task type="auto">
  <name>Task 2: Create useExecution hook and ExecutionStep component</name>
  <files>
    frontend/src/hooks/useExecution.ts
    frontend/src/components/ExecutionStep.tsx
  </files>
  <action>
Create execution state management and step display component:

1. Create frontend/src/hooks/useExecution.ts:
   ```typescript
   import { useState, useCallback, useEffect } from 'react'
   import { useWebSocket } from './useWebSocket'
   import { dashboardApi } from '../api/dashboard'
   import type {
     DashboardPlan,
     PlanStep,
     WSStepStatus,
     WSStepOutput,
     WSPlanCompleted,
     WSPlanFailed,
   } from '../types'

   interface ExecutionSummary {
     total_duration_ms: number
     steps_completed: number
     steps_failed: number
     resources_used: Record<string, unknown>
     audit_trail_url?: string
   }

   interface UseExecutionState {
     plan: DashboardPlan | null
     steps: PlanStep[]
     stepOutputs: Record<number, string[]>
     isExecuting: boolean
     isCompleted: boolean
     isFailed: boolean
     isAborting: boolean
     summary: ExecutionSummary | null
     error: string | null
   }

   interface UseExecutionReturn extends UseExecutionState {
     startExecution: (plan: DashboardPlan) => void
     abort: () => Promise<void>
     clearExecution: () => void
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
     })

     const handleStepStatus = useCallback((message: WSStepStatus) => {
       setState(prev => {
         const newSteps = [...prev.steps]
         if (newSteps[message.step_index]) {
           newSteps[message.step_index] = {
             ...newSteps[message.step_index],
             status: message.status,
             output: message.output,
             error: message.error,
           }
         }
         return { ...prev, steps: newSteps }
       })
     }, [])

     const handleStepOutput = useCallback((message: WSStepOutput) => {
       setState(prev => ({
         ...prev,
         stepOutputs: {
           ...prev.stepOutputs,
           [message.step_index]: [
             ...(prev.stepOutputs[message.step_index] || []),
             message.output,
           ],
         },
       }))
     }, [])

     const handlePlanCompleted = useCallback((message: WSPlanCompleted) => {
       setState(prev => ({
         ...prev,
         isExecuting: false,
         isCompleted: true,
         summary: message.summary,
       }))
     }, [])

     const handlePlanFailed = useCallback((message: WSPlanFailed) => {
       setState(prev => {
         const newSteps = [...prev.steps]
         if (message.failed_step_index !== undefined && newSteps[message.failed_step_index]) {
           newSteps[message.failed_step_index] = {
             ...newSteps[message.failed_step_index],
             status: 'failed',
             error: message.error,
           }
         }
         return {
           ...prev,
           steps: newSteps,
           isExecuting: false,
           isFailed: true,
           error: message.error,
         }
       })
     }, [])

     const ws = useWebSocket({
       sessionId,
       onStepStatus: handleStepStatus,
       onStepOutput: handleStepOutput,
       onPlanCompleted: handlePlanCompleted,
       onPlanFailed: handlePlanFailed,
     })

     const startExecution = useCallback((plan: DashboardPlan) => {
       setState({
         plan,
         steps: plan.steps,
         stepOutputs: {},
         isExecuting: true,
         isCompleted: false,
         isFailed: false,
         isAborting: false,
         summary: null,
         error: null,
       })

       // Subscribe to plan updates
       ws.subscribe(plan.plan_id)
     }, [ws])

     const abort = useCallback(async () => {
       if (!state.plan) return

       setState(prev => ({ ...prev, isAborting: true }))

       try {
         await dashboardApi.abortPlan(state.plan.plan_id)
         setState(prev => ({
           ...prev,
           isExecuting: false,
           isAborting: false,
           error: 'Execution aborted by user',
         }))
       } catch (err) {
         setState(prev => ({
           ...prev,
           isAborting: false,
           error: 'Failed to abort execution',
         }))
       }
     }, [state.plan])

     const clearExecution = useCallback(() => {
       if (state.plan) {
         ws.unsubscribe(state.plan.plan_id)
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
       })
     }, [state.plan, ws])

     return {
       ...state,
       startExecution,
       abort,
       clearExecution,
     }
   }
   ```

2. Create frontend/src/components/ExecutionStep.tsx:
   ```typescript
   import { useState } from 'react'
   import { clsx } from 'clsx'
   import {
     CheckCircle,
     Circle,
     Loader2,
     XCircle,
     MinusCircle,
     ChevronDown,
     ChevronRight,
     Terminal,
   } from 'lucide-react'
   import type { PlanStep } from '../types'

   interface ExecutionStepProps {
     step: PlanStep
     output?: string[]
     isActive?: boolean
   }

   const statusConfig = {
     pending: {
       icon: Circle,
       color: 'text-gray-400',
       bg: 'bg-white border-gray-200',
       label: 'Pending',
     },
     running: {
       icon: Loader2,
       color: 'text-blue-500',
       bg: 'bg-blue-50 border-blue-300',
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
       color: 'text-gray-400',
       bg: 'bg-gray-50 border-gray-200',
       label: 'Skipped',
     },
   }

   export default function ExecutionStep({ step, output = [], isActive }: ExecutionStepProps) {
     const [isExpanded, setIsExpanded] = useState(isActive || step.status === 'failed')
     const config = statusConfig[step.status]
     const Icon = config.icon
     const hasOutput = output.length > 0 || step.output || step.error

     return (
       <div
         className={clsx(
           'border rounded-lg overflow-hidden transition-all',
           config.bg,
           isActive && 'ring-2 ring-blue-400'
         )}
       >
         {/* Header */}
         <div
           className={clsx(
             'flex items-center gap-3 p-4 cursor-pointer',
             hasOutput && 'hover:bg-black/5'
           )}
           onClick={() => hasOutput && setIsExpanded(!isExpanded)}
         >
           <div className={clsx('flex-shrink-0', config.color)}>
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
               <span
                 className={clsx(
                   'text-xs px-2 py-0.5 rounded-full',
                   step.status === 'running' && 'bg-blue-100 text-blue-700',
                   step.status === 'completed' && 'bg-green-100 text-green-700',
                   step.status === 'failed' && 'bg-red-100 text-red-700'
                 )}
               >
                 {config.label}
               </span>
               {step.duration_ms && (
                 <span className="text-xs text-gray-400">
                   {(step.duration_ms / 1000).toFixed(1)}s
                 </span>
               )}
             </div>
             <h4 className="font-medium text-gray-900">{step.name}</h4>
             <p className="text-sm text-gray-600">{step.description}</p>
           </div>

           {hasOutput && (
             <div className="flex-shrink-0 text-gray-400">
               {isExpanded ? (
                 <ChevronDown className="w-5 h-5" />
               ) : (
                 <ChevronRight className="w-5 h-5" />
               )}
             </div>
           )}
         </div>

         {/* Expanded content */}
         {isExpanded && hasOutput && (
           <div className="border-t bg-gray-900 p-4">
             {/* Live output stream */}
             {output.length > 0 && (
               <div className="mb-4">
                 <div className="flex items-center gap-2 text-gray-400 text-xs mb-2">
                   <Terminal className="w-4 h-4" />
                   <span>Live Output</span>
                 </div>
                 <pre className="text-xs text-gray-100 font-mono whitespace-pre-wrap max-h-96 overflow-y-auto">
                   {output.join('')}
                 </pre>
               </div>
             )}

             {/* Final output */}
             {step.output && (
               <div className="mb-4">
                 <div className="text-gray-400 text-xs mb-2">Output</div>
                 <pre className="text-xs text-gray-100 font-mono whitespace-pre-wrap max-h-48 overflow-y-auto">
                   {step.output}
                 </pre>
               </div>
             )}

             {/* Error */}
             {step.error && (
               <div className="bg-red-900/30 border border-red-700 rounded p-3">
                 <div className="text-red-400 text-xs mb-1">Error</div>
                 <pre className="text-xs text-red-200 font-mono whitespace-pre-wrap">
                   {step.error}
                 </pre>
               </div>
             )}
           </div>
         )}
       </div>
     )
   }
   ```
  </action>
  <verify>
    - [ ] useExecution tracks execution state and step updates
    - [ ] WebSocket messages update step status correctly
    - [ ] Abort function calls API and updates state
    - [ ] ExecutionStep renders with correct status styling
    - [ ] Output expandable and scrollable
  </verify>
  <done>useExecution hook and ExecutionStep component created</done>
</task>

<task type="auto">
  <name>Task 3: Create ExecutionMonitor and ExecutionSummary components</name>
  <files>
    frontend/src/components/ExecutionMonitor.tsx
    frontend/src/components/ExecutionSummary.tsx
    frontend/src/App.tsx
    tests/frontend/ExecutionMonitor.test.tsx
  </files>
  <action>
Create the main execution monitoring component and post-execution summary:

1. Create frontend/src/components/ExecutionSummary.tsx:
   ```typescript
   import { clsx } from 'clsx'
   import {
     CheckCircle,
     XCircle,
     Clock,
     Cpu,
     ExternalLink,
     FileText,
   } from 'lucide-react'

   interface ExecutionSummaryProps {
     summary: {
       total_duration_ms: number
       steps_completed: number
       steps_failed: number
       resources_used: Record<string, unknown>
       audit_trail_url?: string
     }
     onClose: () => void
   }

   export default function ExecutionSummary({ summary, onClose }: ExecutionSummaryProps) {
     const isSuccess = summary.steps_failed === 0

     return (
       <div className="bg-white rounded-xl border shadow-sm overflow-hidden">
         {/* Header */}
         <div
           className={clsx(
             'p-6 border-b',
             isSuccess ? 'bg-green-50' : 'bg-red-50'
           )}
         >
           <div className="flex items-center gap-3">
             {isSuccess ? (
               <CheckCircle className="w-8 h-8 text-green-500" />
             ) : (
               <XCircle className="w-8 h-8 text-red-500" />
             )}
             <div>
               <h2 className="text-xl font-semibold text-gray-900">
                 {isSuccess ? 'Execution Completed' : 'Execution Failed'}
               </h2>
               <p className="text-gray-600">
                 {summary.steps_completed} of {summary.steps_completed + summary.steps_failed} steps completed
               </p>
             </div>
           </div>
         </div>

         {/* Stats */}
         <div className="p-6 grid grid-cols-2 md:grid-cols-4 gap-4">
           <div className="bg-gray-50 rounded-lg p-4">
             <div className="flex items-center gap-2 text-gray-500 text-sm mb-1">
               <Clock className="w-4 h-4" />
               Duration
             </div>
             <div className="text-2xl font-semibold text-gray-900">
               {(summary.total_duration_ms / 1000).toFixed(1)}s
             </div>
           </div>

           <div className="bg-gray-50 rounded-lg p-4">
             <div className="flex items-center gap-2 text-gray-500 text-sm mb-1">
               <CheckCircle className="w-4 h-4" />
               Completed
             </div>
             <div className="text-2xl font-semibold text-green-600">
               {summary.steps_completed}
             </div>
           </div>

           <div className="bg-gray-50 rounded-lg p-4">
             <div className="flex items-center gap-2 text-gray-500 text-sm mb-1">
               <XCircle className="w-4 h-4" />
               Failed
             </div>
             <div className="text-2xl font-semibold text-red-600">
               {summary.steps_failed}
             </div>
           </div>

           <div className="bg-gray-50 rounded-lg p-4">
             <div className="flex items-center gap-2 text-gray-500 text-sm mb-1">
               <Cpu className="w-4 h-4" />
               Resources
             </div>
             <div className="text-sm text-gray-700">
               {Object.entries(summary.resources_used).map(([key, value]) => (
                 <div key={key}>{key}: {String(value)}</div>
               ))}
             </div>
           </div>
         </div>

         {/* Audit trail link */}
         {summary.audit_trail_url && (
           <div className="px-6 pb-6">
             <a
               href={summary.audit_trail_url}
               target="_blank"
               rel="noopener noreferrer"
               className="flex items-center gap-2 text-chiffon-primary hover:underline"
             >
               <FileText className="w-4 h-4" />
               View Audit Trail
               <ExternalLink className="w-3 h-3" />
             </a>
           </div>
         )}

         {/* Actions */}
         <div className="p-6 border-t bg-gray-50">
           <button
             onClick={onClose}
             className="px-6 py-2 bg-chiffon-primary text-white rounded-lg hover:bg-chiffon-secondary"
           >
             Start New Request
           </button>
         </div>
       </div>
     )
   }
   ```

2. Create frontend/src/components/ExecutionMonitor.tsx:
   ```typescript
   import { useEffect } from 'react'
   import { clsx } from 'clsx'
   import { Loader2, StopCircle, AlertCircle, Wifi, WifiOff } from 'lucide-react'
   import type { DashboardPlan } from '../types'
   import { useExecution } from '../hooks/useExecution'
   import ExecutionStep from './ExecutionStep'
   import ExecutionSummary from './ExecutionSummary'

   interface ExecutionMonitorProps {
     plan: DashboardPlan
     sessionId: string
     onComplete: () => void
   }

   export default function ExecutionMonitor({
     plan,
     sessionId,
     onComplete,
   }: ExecutionMonitorProps) {
     const execution = useExecution(sessionId)

     // Start execution when component mounts
     useEffect(() => {
       execution.startExecution(plan)
       return () => execution.clearExecution()
     }, [plan.plan_id])

     // Show summary when completed
     if (execution.isCompleted && execution.summary) {
       return (
         <ExecutionSummary
           summary={execution.summary}
           onClose={() => {
             execution.clearExecution()
             onComplete()
           }}
         />
       )
     }

     // Find currently running step
     const activeStepIndex = execution.steps.findIndex(s => s.status === 'running')

     return (
       <div className="bg-white rounded-xl border shadow-sm overflow-hidden">
         {/* Header */}
         <div className="p-6 border-b bg-gray-50">
           <div className="flex items-center justify-between">
             <div>
               <h2 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
                 <Loader2 className="w-5 h-5 animate-spin text-blue-500" />
                 Executing Plan
               </h2>
               <p className="text-gray-600 mt-1">{plan.summary}</p>
             </div>

             {/* Abort button */}
             {execution.isExecuting && !execution.isAborting && (
               <button
                 onClick={execution.abort}
                 className="flex items-center gap-2 px-4 py-2 bg-red-100 text-red-700 rounded-lg hover:bg-red-200"
               >
                 <StopCircle className="w-4 h-4" />
                 Abort
               </button>
             )}

             {execution.isAborting && (
               <div className="flex items-center gap-2 text-red-600">
                 <Loader2 className="w-4 h-4 animate-spin" />
                 Aborting...
               </div>
             )}
           </div>

           {/* Progress bar */}
           <div className="mt-4">
             <div className="flex justify-between text-sm text-gray-500 mb-1">
               <span>Progress</span>
               <span>
                 {execution.steps.filter(s => s.status === 'completed').length} / {execution.steps.length}
               </span>
             </div>
             <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
               <div
                 className="h-full bg-green-500 transition-all duration-300"
                 style={{
                   width: `${
                     (execution.steps.filter(s => s.status === 'completed').length /
                       execution.steps.length) *
                     100
                   }%`,
                 }}
               />
             </div>
           </div>
         </div>

         {/* Error banner */}
         {execution.error && (
           <div className="px-6 py-4 bg-red-50 border-b border-red-200">
             <div className="flex items-center gap-2 text-red-700">
               <AlertCircle className="w-5 h-5" />
               <span>{execution.error}</span>
             </div>
           </div>
         )}

         {/* Steps */}
         <div className="p-6 space-y-3">
           {execution.steps.map((step, index) => (
             <ExecutionStep
               key={step.index}
               step={step}
               output={execution.stepOutputs[index]}
               isActive={index === activeStepIndex}
             />
           ))}
         </div>

         {/* Failed state */}
         {execution.isFailed && (
           <div className="p-6 border-t bg-red-50">
             <div className="flex items-center gap-2 text-red-700 mb-4">
               <AlertCircle className="w-5 h-5" />
               <span className="font-medium">Execution failed</span>
             </div>
             <button
               onClick={() => {
                 execution.clearExecution()
                 onComplete()
               }}
               className="px-4 py-2 bg-white border rounded-lg hover:bg-gray-50"
             >
               Return to Chat
             </button>
           </div>
         )}
       </div>
     )
   }
   ```

3. Update frontend/src/App.tsx to integrate ExecutionMonitor:
   - Add 'executing' to view state type
   - Render ExecutionMonitor when plan.status === 'executing' or 'approved'
   - Handle execution completion

4. Create tests/frontend/ExecutionMonitor.test.tsx:
   ```typescript
   import { describe, it, expect, vi, beforeEach } from 'vitest'
   import { render, screen, fireEvent, waitFor } from '@testing-library/react'
   import ExecutionMonitor from '../../src/components/ExecutionMonitor'
   import type { DashboardPlan } from '../../src/types'

   // Mock WebSocket
   const mockWs = {
     send: vi.fn(),
     close: vi.fn(),
     addEventListener: vi.fn(),
     removeEventListener: vi.fn(),
   }

   vi.stubGlobal('WebSocket', vi.fn(() => mockWs))

   const mockPlan: DashboardPlan = {
     plan_id: 'test-plan',
     request_id: 'test-request',
     summary: 'Deploy Kuma',
     steps: [
       { index: 0, name: 'Step 1', description: 'First step', status: 'running' },
       { index: 1, name: 'Step 2', description: 'Second step', status: 'pending' },
     ],
     estimated_duration: '~2 minutes',
     risk_level: 'low',
     resource_requirements: {},
     status: 'executing',
     can_approve: false,
     can_modify: false,
     can_abort: true,
   }

   describe('ExecutionMonitor', () => {
     beforeEach(() => {
       vi.clearAllMocks()
     })

     it('renders executing state', () => {
       render(
         <ExecutionMonitor
           plan={mockPlan}
           sessionId="test-session"
           onComplete={vi.fn()}
         />
       )

       expect(screen.getByText('Executing Plan')).toBeInTheDocument()
       expect(screen.getByText('Deploy Kuma')).toBeInTheDocument()
     })

     it('shows abort button during execution', () => {
       render(
         <ExecutionMonitor
           plan={mockPlan}
           sessionId="test-session"
           onComplete={vi.fn()}
         />
       )

       expect(screen.getByText('Abort')).toBeInTheDocument()
     })

     it('renders all steps', () => {
       render(
         <ExecutionMonitor
           plan={mockPlan}
           sessionId="test-session"
           onComplete={vi.fn()}
         />
       )

       expect(screen.getByText('Step 1')).toBeInTheDocument()
       expect(screen.getByText('Step 2')).toBeInTheDocument()
     })

     it('shows progress bar', () => {
       render(
         <ExecutionMonitor
           plan={mockPlan}
           sessionId="test-session"
           onComplete={vi.fn()}
         />
       )

       expect(screen.getByText('0 / 2')).toBeInTheDocument()
     })
   })
   ```
  </action>
  <verify>
    - [ ] ExecutionMonitor shows real-time step status
    - [ ] Progress bar updates as steps complete
    - [ ] Abort button calls abort function
    - [ ] ExecutionSummary shows after completion
    - [ ] Audit trail link present in summary
    - [ ] All tests pass: `cd frontend && npm test`
  </verify>
  <done>ExecutionMonitor and ExecutionSummary created with full monitoring support</done>
</task>

</tasks>

<verification>
After all tasks complete:
1. Start frontend: `cd frontend && npm run dev`
2. Start dashboard backend with WebSocket: `uvicorn src.dashboard.main:app --port 8001`
3. Submit request, approve plan, observe execution monitoring
4. Verify real-time updates via WebSocket
5. Run tests: `npm test`
</verification>

<success_criteria>
- Real-time step status updates during execution
- Live output streaming to step expandable sections
- Abort button stops execution
- Post-execution summary shows duration, resources, outcome
- Audit trail link present in summary
- Polling fallback works when WebSocket unavailable
- All tests pass (target: 15+ test cases)
</success_criteria>

<output>
After completion, create `.planning/phases/07-user-interface/07-05-SUMMARY.md`
</output>
