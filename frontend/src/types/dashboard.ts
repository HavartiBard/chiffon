export interface ChatMessage {
  id: string
  sessionId: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: string
  metadata?: Record<string, unknown>
}

export interface ChatSession {
  sessionId: string
  userId: string
  createdAt: string
  lastActivity: string
  messages: ChatMessage[]
  status: 'idle' | 'awaiting_plan' | 'plan_ready' | 'executing' | 'completed'
  currentPlanId?: string
}

export interface PlanStep {
  index: number
  name: string
  description: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped'
  durationMs?: number
  output?: string
  error?: string
  metadata?: Record<string, unknown>
}

export interface PlanView {
  planId: string
  requestId: string
  summary: string
  steps: PlanStep[]
  estimatedDuration: string
  riskLevel: 'low' | 'medium' | 'high'
  resourceRequirements: Record<string, unknown>
  status: string
  canApprove: boolean
  canModify: boolean
  canAbort: boolean
}

export interface ExecutionEvent {
  type: string
  data: Record<string, unknown>
  timestamp?: string
}

export type WSMessageType =
  | 'subscribed'
  | 'unsubscribed'
  | 'step_status'
  | 'step_output'
  | 'plan_completed'
  | 'plan_failed'
  | 'execution_started'
  | 'execution_done'
  | 'error'
  | 'pong'

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

export interface ChatResponse {
  messages: ChatMessage[]
  plan?: PlanView
}

export interface PlanEventPayload {
  event: string
  plan_id?: string
  subscription_id?: string
  data?: Record<string, unknown>
}

export interface PlanStatusPayload {
  overall_status: string
  steps: PlanStep[]
  last_update?: string
}

export interface ExecutionSummaryPayload {
  total_duration_ms: number
  steps_completed: number
  steps_failed: number
  resources_used: Record<string, unknown>
  audit_trail_url?: string
  postgres_record_url?: string
  task_ids?: string[]
}
