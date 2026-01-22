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

export interface ChatResponse {
  messages: ChatMessage[]
  plan?: PlanView
}
