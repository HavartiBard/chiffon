import axios, { AxiosError } from 'axios'
import type { ChatResponse, PlanStatusPayload, PlanView } from '../types/dashboard'

const dashboardClient = axios.create({
  baseURL: 'http://localhost:8001/api/dashboard',
  timeout: 30_000,
})

dashboardClient.interceptors.request.use((config) => {
  console.debug('Dashboard request', config.method, config.url, config.data)
  return config
})

dashboardClient.interceptors.response.use(
  (response) => {
    console.debug('Dashboard response', response.status, response.config.url)
    return response
  },
  (error: AxiosError) => {
    console.error('Dashboard response error', error.message, error.config?.url)
    return Promise.reject(error)
  }
)

async function withRetry<T>(fn: () => Promise<T>): Promise<T> {
  let attempt = 0
  let lastError: unknown
  while (attempt < 3) {
    try {
      return await fn()
    } catch (error) {
      lastError = error
      if (
        axios.isAxiosError(error) &&
        error.response &&
        error.response.status >= 500 &&
        attempt < 2
      ) {
        attempt += 1
        continue
      }
      throw error
    }
  }
  throw lastError
}

const dashboardApi = {
  async createSession(userId: string) {
    const response = await withRetry(() =>
      dashboardClient.post('/session', { user_id: userId })
    )
    return response.data
  },

  async sendMessage(sessionId: string, message: string): Promise<ChatResponse> {
    const response = await withRetry(() =>
      dashboardClient.post('/chat', { session_id: sessionId, message })
    )
    return response.data
  },

  async getPlan(planId: string): Promise<PlanView> {
    const response = await withRetry(() => dashboardClient.get(`/plan/${planId}`))
    return response.data
  },

  async approvePlan(planId: string, sessionId: string): Promise<{ status: string; execution_started: boolean }> {
    const response = await withRetry(() => dashboardClient.post(`/plan/${planId}/approve`, { session_id: sessionId }))
    return response.data
  },

  async rejectPlan(planId: string, sessionId: string): Promise<{ status: string }> {
    const response = await withRetry(() => dashboardClient.post(`/plan/${planId}/reject`, { session_id: sessionId }))
    return response.data
  },

  async modifyPlan(planId: string, sessionId: string, modification: string): Promise<{ new_plan: PlanView }> {
    const response = await withRetry(() =>
      dashboardClient.post(`/plan/${planId}/modify`, {
        plan_id: planId,
        session_id: sessionId,
        user_message: modification,
      })
    )
    return response.data
  },

  async pollPlan(planId: string): Promise<PlanStatusPayload> {
    const response = await withRetry(() => dashboardClient.get(`/plan/${planId}/poll`))
    return response.data
  },
}

export { dashboardApi }
