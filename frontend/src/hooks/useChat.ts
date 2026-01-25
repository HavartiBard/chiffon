import { useCallback, useEffect, useState } from 'react'
import { dashboardApi } from '../api/dashboardClient'
import type { ChatMessage, ChatSession, PlanView } from '../types/dashboard'

interface UseChatState {
  session: ChatSession | null
  messages: ChatMessage[]
  plan: PlanView | null
  isLoading: boolean
  error: string | null
}

interface UseChatReturn extends UseChatState {
  sendMessage: (content: string) => Promise<void>
  clearHistory: () => void
}

const normalizeSession = (payload: any): ChatSession => ({
  sessionId: payload.session_id,
  userId: payload.user_id,
  createdAt: payload.created_at,
  lastActivity: payload.last_activity,
  messages: (payload.messages || []).map((message: any) => normalizeMessage(message)),
  status: payload.status,
  currentPlanId: payload.current_plan_id,
})

const normalizeMessage = (message: any): ChatMessage => ({
  id: message.id,
  sessionId: message.session_id,
  role: message.role,
  content: message.content,
  timestamp: message.timestamp,
  metadata: message.metadata,
})

export function useChat(userId: string = 'web-user'): UseChatReturn {
  const [state, setState] = useState<UseChatState>({
    session: null,
    messages: [],
    plan: null,
    isLoading: false,
    error: null,
  })

  const initializeSession = useCallback(async () => {
    setState((prev) => ({ ...prev, isLoading: true, error: null }))
    try {
      const sessionPayload = await dashboardApi.createSession(userId)
      const session = normalizeSession(sessionPayload)
      setState({
        session,
        messages: session.messages,
        plan: null,
        isLoading: false,
        error: null,
      })
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error'
      setState((prev) => ({ ...prev, isLoading: false, error: `Failed to create session: ${message}` }))
    }
  }, [userId])

  useEffect(() => {
    initializeSession()
  }, [initializeSession])

  const sendMessage = useCallback(
    async (content: string) => {
      if (!state.session || !content.trim()) {
        return
      }

      setState((prev) => ({ ...prev, isLoading: true, error: null }))

      const optimistic: ChatMessage = {
        id: `temp-${Date.now()}`,
        sessionId: state.session.sessionId,
        role: 'user',
        content: content.trim(),
        timestamp: new Date().toISOString(),
      }

      setState((prev) => ({
        ...prev,
        messages: [...prev.messages, optimistic],
      }))

      try {
        const response = await dashboardApi.sendMessage(state.session.sessionId, content.trim())
        const normalized = response.messages.map(normalizeMessage)
        setState((prev) => ({
          ...prev,
          messages: [...prev.messages.filter((m) => !m.id.startsWith('temp-')), ...normalized],
          plan: response.plan ?? prev.plan,
          isLoading: false,
        }))
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Unknown error'
        setState((prev) => ({
          ...prev,
          isLoading: false,
          error: `Chat failed: ${message}`,
          messages: [
            ...prev.messages,
            {
              id: `error-${Date.now()}`,
              sessionId: state.session!.sessionId,
              role: 'system',
              content: `Error: ${message}`,
              timestamp: new Date().toISOString(),
              metadata: { error: true },
            },
          ],
        }))
      }
    },
    [state.session]
  )

  const clearHistory = useCallback(() => {
    setState((prev) => ({ ...prev, messages: [], plan: null }))
  }, [])

  return {
    ...state,
    sendMessage,
    clearHistory,
  }
}
