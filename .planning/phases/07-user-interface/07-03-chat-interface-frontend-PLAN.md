# Phase 7 Plan 03: Chat Interface Frontend

---
phase: 07-user-interface
plan: 03
type: execute
wave: 2
depends_on: ["07-01"]
files_modified:
  - frontend/package.json
  - frontend/src/App.tsx
  - frontend/src/components/Chat.tsx
  - frontend/src/components/ChatMessage.tsx
  - frontend/src/components/ChatInput.tsx
  - frontend/src/hooks/useChat.ts
  - frontend/src/api/dashboard.ts
  - frontend/src/types/index.ts
  - frontend/vite.config.ts
  - frontend/tailwind.config.js
  - tests/frontend/Chat.test.tsx
autonomous: true
must_haves:
  truths:
    - "Chat interface renders and accepts user input"
    - "Messages displayed in conversation format (user/assistant)"
    - "Deployment requests submitted via chat input"
    - "Loading states shown during request processing"
    - "Error states displayed clearly to user"
  artifacts:
    - path: "frontend/src/components/Chat.tsx"
      provides: "Main chat interface component"
    - path: "frontend/src/hooks/useChat.ts"
      provides: "Chat state management hook"
    - path: "frontend/src/api/dashboard.ts"
      provides: "Dashboard API client"
  key_links:
    - from: "frontend/src/hooks/useChat.ts"
      to: "frontend/src/api/dashboard.ts"
      via: "API calls"
      pattern: "dashboardApi"
    - from: "frontend/src/components/Chat.tsx"
      to: "frontend/src/hooks/useChat.ts"
      via: "hook consumption"
      pattern: "useChat"
---

<objective>
Create the React frontend chat interface that accepts natural language deployment requests. The chat is the primary user interaction point - users describe what they want deployed and receive plan summaries for approval.

Purpose: This satisfies UI-01 (chat interface accepts deployment requests in natural language). The chat interface is the user's conversational window into the orchestrator.

Output: Working React chat component with message display, input handling, API integration, and loading/error states.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@src/dashboard/api.py
@src/dashboard/models.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Initialize React frontend with Vite and dependencies</name>
  <files>
    frontend/package.json
    frontend/vite.config.ts
    frontend/tailwind.config.js
    frontend/src/main.tsx
    frontend/src/App.tsx
    frontend/src/index.css
    frontend/tsconfig.json
  </files>
  <action>
Initialize the React frontend with Vite, TypeScript, and TailwindCSS:

1. Create frontend/ directory structure:
   ```
   frontend/
   ├── src/
   │   ├── components/
   │   ├── hooks/
   │   ├── api/
   │   ├── types/
   │   ├── App.tsx
   │   ├── main.tsx
   │   └── index.css
   ├── package.json
   ├── vite.config.ts
   ├── tailwind.config.js
   ├── tsconfig.json
   └── index.html
   ```

2. Create frontend/package.json:
   ```json
   {
     "name": "chiffon-dashboard",
     "version": "0.1.0",
     "type": "module",
     "scripts": {
       "dev": "vite",
       "build": "tsc && vite build",
       "preview": "vite preview",
       "test": "vitest",
       "lint": "eslint src --ext .ts,.tsx"
     },
     "dependencies": {
       "react": "^18.2.0",
       "react-dom": "^18.2.0",
       "axios": "^1.6.0",
       "clsx": "^2.0.0",
       "lucide-react": "^0.294.0"
     },
     "devDependencies": {
       "@types/react": "^18.2.0",
       "@types/react-dom": "^18.2.0",
       "@vitejs/plugin-react": "^4.2.0",
       "autoprefixer": "^10.4.16",
       "postcss": "^8.4.32",
       "tailwindcss": "^3.3.6",
       "typescript": "^5.3.0",
       "vite": "^5.0.0",
       "vitest": "^1.0.0",
       "@testing-library/react": "^14.1.0",
       "@testing-library/jest-dom": "^6.1.0"
     }
   }
   ```

3. Create frontend/vite.config.ts:
   ```typescript
   import { defineConfig } from 'vite'
   import react from '@vitejs/plugin-react'

   export default defineConfig({
     plugins: [react()],
     server: {
       port: 3000,
       proxy: {
         '/api': {
           target: 'http://localhost:8001',
           changeOrigin: true,
         },
         '/ws': {
           target: 'ws://localhost:8001',
           ws: true,
         },
       },
     },
   })
   ```

4. Create frontend/tailwind.config.js:
   ```javascript
   /** @type {import('tailwindcss').Config} */
   export default {
     content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
     theme: {
       extend: {
         colors: {
           'chiffon-primary': '#6366f1',
           'chiffon-secondary': '#8b5cf6',
         },
       },
     },
     plugins: [],
   }
   ```

5. Create frontend/src/index.css with Tailwind directives:
   ```css
   @tailwind base;
   @tailwind components;
   @tailwind utilities;

   body {
     @apply bg-gray-50 text-gray-900;
   }
   ```

6. Create frontend/src/main.tsx:
   ```typescript
   import React from 'react'
   import ReactDOM from 'react-dom/client'
   import App from './App'
   import './index.css'

   ReactDOM.createRoot(document.getElementById('root')!).render(
     <React.StrictMode>
       <App />
     </React.StrictMode>,
   )
   ```

7. Create frontend/src/App.tsx (placeholder):
   ```typescript
   import Chat from './components/Chat'

   function App() {
     return (
       <div className="min-h-screen bg-gray-50">
         <header className="bg-white shadow-sm border-b">
           <div className="max-w-4xl mx-auto px-4 py-4">
             <h1 className="text-xl font-semibold text-gray-900">
               Chiffon Dashboard
             </h1>
           </div>
         </header>
         <main className="max-w-4xl mx-auto px-4 py-8">
           <Chat />
         </main>
       </div>
     )
   }

   export default App
   ```

8. Create frontend/index.html:
   ```html
   <!DOCTYPE html>
   <html lang="en">
     <head>
       <meta charset="UTF-8" />
       <meta name="viewport" content="width=device-width, initial-scale=1.0" />
       <title>Chiffon Dashboard</title>
     </head>
     <body>
       <div id="root"></div>
       <script type="module" src="/src/main.tsx"></script>
     </body>
   </html>
   ```
  </action>
  <verify>
    - [ ] `cd frontend && npm install` completes
    - [ ] `npm run dev` starts dev server on port 3000
    - [ ] Page loads with "Chiffon Dashboard" header
    - [ ] TailwindCSS styles applied
  </verify>
  <done>React frontend initialized with Vite, TypeScript, and TailwindCSS</done>
</task>

<task type="auto">
  <name>Task 2: Create API client and TypeScript types</name>
  <files>
    frontend/src/types/index.ts
    frontend/src/api/dashboard.ts
  </files>
  <action>
Create TypeScript types and API client for dashboard communication:

1. Create frontend/src/types/index.ts:
   ```typescript
   export interface ChatMessage {
     id: string
     role: 'user' | 'assistant' | 'system'
     content: string
     timestamp: string
     metadata?: {
       plan_id?: string
       request_id?: string
       error?: boolean
     }
   }

   export interface ChatSession {
     session_id: string
     user_id: string
     created_at: string
     last_activity: string
     messages: ChatMessage[]
     current_request_id?: string
     current_plan_id?: string
     status: 'idle' | 'awaiting_plan' | 'plan_ready' | 'executing' | 'completed'
   }

   export interface PlanStep {
     index: number
     name: string
     description: string
     status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped'
     duration_ms?: number
     output?: string
     error?: string
   }

   export interface DashboardPlan {
     plan_id: string
     request_id: string
     summary: string
     steps: PlanStep[]
     estimated_duration: string
     risk_level: 'low' | 'medium' | 'high'
     resource_requirements: Record<string, unknown>
     status: string
     can_approve: boolean
     can_modify: boolean
     can_abort: boolean
   }

   export interface ChatResponse {
     messages: ChatMessage[]
     plan?: DashboardPlan
   }

   export interface ApiError {
     detail: string
     status: number
   }
   ```

2. Create frontend/src/api/dashboard.ts:
   ```typescript
   import axios, { AxiosError } from 'axios'
   import type { ChatSession, ChatResponse, DashboardPlan, ApiError } from '../types'

   const api = axios.create({
     baseURL: '/api/dashboard',
     timeout: 30000,
     headers: {
       'Content-Type': 'application/json',
     },
   })

   // Error handling wrapper
   function handleApiError(error: unknown): never {
     if (axios.isAxiosError(error)) {
       const axiosError = error as AxiosError<{ detail: string }>
       throw {
         detail: axiosError.response?.data?.detail || axiosError.message,
         status: axiosError.response?.status || 500,
       } as ApiError
     }
     throw { detail: 'Unknown error', status: 500 } as ApiError
   }

   export const dashboardApi = {
     // Session management
     async createSession(userId: string): Promise<ChatSession> {
       try {
         const response = await api.post<ChatSession>('/session', { user_id: userId })
         return response.data
       } catch (error) {
         throw handleApiError(error)
       }
     },

     async getSession(sessionId: string): Promise<ChatSession> {
       try {
         const response = await api.get<ChatSession>(`/session/${sessionId}`)
         return response.data
       } catch (error) {
         throw handleApiError(error)
       }
     },

     // Chat
     async sendMessage(sessionId: string, message: string): Promise<ChatResponse> {
       try {
         const response = await api.post<ChatResponse>('/chat', {
           session_id: sessionId,
           message,
         })
         return response.data
       } catch (error) {
         throw handleApiError(error)
       }
     },

     // Plan operations
     async getPlan(planId: string): Promise<DashboardPlan> {
       try {
         const response = await api.get<DashboardPlan>(`/plan/${planId}`)
         return response.data
       } catch (error) {
         throw handleApiError(error)
       }
     },

     async approvePlan(planId: string): Promise<{ status: string; execution_started: boolean }> {
       try {
         const response = await api.post(`/plan/${planId}/approve`)
         return response.data
       } catch (error) {
         throw handleApiError(error)
       }
     },

     async rejectPlan(planId: string): Promise<{ status: string }> {
       try {
         const response = await api.post(`/plan/${planId}/reject`)
         return response.data
       } catch (error) {
         throw handleApiError(error)
       }
     },

     async modifyPlan(planId: string, sessionId: string, modification: string): Promise<{ new_plan: DashboardPlan }> {
       try {
         const response = await api.post(`/plan/${planId}/modify`, {
           plan_id: planId,
           session_id: sessionId,
           user_message: modification,
         })
         return response.data
       } catch (error) {
         throw handleApiError(error)
       }
     },

     async abortPlan(planId: string): Promise<{ status: string }> {
       try {
         const response = await api.post(`/plan/${planId}/abort`)
         return response.data
       } catch (error) {
         throw handleApiError(error)
       }
     },

     // Polling fallback
     async pollStatus(planId: string): Promise<DashboardPlan> {
       try {
         const response = await api.get<DashboardPlan>(`/plan/${planId}/poll`)
         return response.data
       } catch (error) {
         throw handleApiError(error)
       }
     },
   }
   ```
  </action>
  <verify>
    - [ ] TypeScript types compile without errors
    - [ ] API client exports all required methods
    - [ ] Error handling wraps axios errors correctly
    - [ ] Import works: `import { dashboardApi } from './api/dashboard'`
  </verify>
  <done>API client and TypeScript types created</done>
</task>

<task type="auto">
  <name>Task 3: Create Chat components and useChat hook</name>
  <files>
    frontend/src/hooks/useChat.ts
    frontend/src/components/Chat.tsx
    frontend/src/components/ChatMessage.tsx
    frontend/src/components/ChatInput.tsx
    tests/frontend/Chat.test.tsx
  </files>
  <action>
Create the chat interface components and state management:

1. Create frontend/src/hooks/useChat.ts:
   ```typescript
   import { useState, useEffect, useCallback } from 'react'
   import { dashboardApi } from '../api/dashboard'
   import type { ChatMessage, ChatSession, DashboardPlan, ApiError } from '../types'

   interface UseChatState {
     session: ChatSession | null
     messages: ChatMessage[]
     currentPlan: DashboardPlan | null
     isLoading: boolean
     error: string | null
   }

   interface UseChatReturn extends UseChatState {
     sendMessage: (content: string) => Promise<void>
     clearError: () => void
     initializeSession: () => Promise<void>
   }

   export function useChat(userId: string = 'default-user'): UseChatReturn {
     const [state, setState] = useState<UseChatState>({
       session: null,
       messages: [],
       currentPlan: null,
       isLoading: false,
       error: null,
     })

     const initializeSession = useCallback(async () => {
       setState(prev => ({ ...prev, isLoading: true, error: null }))

       try {
         const session = await dashboardApi.createSession(userId)
         setState(prev => ({
           ...prev,
           session,
           messages: session.messages || [],
           isLoading: false,
         }))
       } catch (err) {
         const apiError = err as ApiError
         setState(prev => ({
           ...prev,
           isLoading: false,
           error: `Failed to initialize session: ${apiError.detail}`,
         }))
       }
     }, [userId])

     useEffect(() => {
       initializeSession()
     }, [initializeSession])

     const sendMessage = useCallback(async (content: string) => {
       if (!state.session || !content.trim()) return

       // Add user message immediately (optimistic update)
       const userMessage: ChatMessage = {
         id: `temp-${Date.now()}`,
         role: 'user',
         content: content.trim(),
         timestamp: new Date().toISOString(),
       }

       setState(prev => ({
         ...prev,
         messages: [...prev.messages, userMessage],
         isLoading: true,
         error: null,
       }))

       try {
         const response = await dashboardApi.sendMessage(
           state.session.session_id,
           content.trim()
         )

         setState(prev => ({
           ...prev,
           messages: [
             ...prev.messages.slice(0, -1), // Remove temp message
             ...response.messages,
           ],
           currentPlan: response.plan || prev.currentPlan,
           isLoading: false,
         }))
       } catch (err) {
         const apiError = err as ApiError
         // Add error message to chat
         const errorMessage: ChatMessage = {
           id: `error-${Date.now()}`,
           role: 'system',
           content: `Error: ${apiError.detail}`,
           timestamp: new Date().toISOString(),
           metadata: { error: true },
         }

         setState(prev => ({
           ...prev,
           messages: [...prev.messages, errorMessage],
           isLoading: false,
           error: apiError.detail,
         }))
       }
     }, [state.session])

     const clearError = useCallback(() => {
       setState(prev => ({ ...prev, error: null }))
     }, [])

     return {
       ...state,
       sendMessage,
       clearError,
       initializeSession,
     }
   }
   ```

2. Create frontend/src/components/ChatMessage.tsx:
   ```typescript
   import { clsx } from 'clsx'
   import { User, Bot, AlertCircle } from 'lucide-react'
   import type { ChatMessage as ChatMessageType } from '../types'

   interface ChatMessageProps {
     message: ChatMessageType
   }

   export default function ChatMessage({ message }: ChatMessageProps) {
     const isUser = message.role === 'user'
     const isError = message.metadata?.error

     return (
       <div
         className={clsx(
           'flex gap-3 p-4 rounded-lg',
           isUser ? 'bg-chiffon-primary/10' : 'bg-white',
           isError && 'bg-red-50 border border-red-200'
         )}
       >
         <div
           className={clsx(
             'w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0',
             isUser ? 'bg-chiffon-primary text-white' : 'bg-gray-200 text-gray-600',
             isError && 'bg-red-200 text-red-600'
           )}
         >
           {isError ? (
             <AlertCircle className="w-4 h-4" />
           ) : isUser ? (
             <User className="w-4 h-4" />
           ) : (
             <Bot className="w-4 h-4" />
           )}
         </div>
         <div className="flex-1 min-w-0">
           <div className="text-sm text-gray-500 mb-1">
             {isUser ? 'You' : isError ? 'System' : 'Chiffon'}
           </div>
           <div
             className={clsx(
               'prose prose-sm max-w-none',
               isError && 'text-red-700'
             )}
           >
             {message.content}
           </div>
           {message.metadata?.plan_id && (
             <div className="mt-2 text-xs text-gray-400">
               Plan: {message.metadata.plan_id}
             </div>
           )}
         </div>
       </div>
     )
   }
   ```

3. Create frontend/src/components/ChatInput.tsx:
   ```typescript
   import { useState, useRef, useEffect, KeyboardEvent } from 'react'
   import { Send, Loader2 } from 'lucide-react'
   import { clsx } from 'clsx'

   interface ChatInputProps {
     onSend: (message: string) => void
     isLoading: boolean
     placeholder?: string
   }

   export default function ChatInput({
     onSend,
     isLoading,
     placeholder = 'Describe what you want to deploy...',
   }: ChatInputProps) {
     const [input, setInput] = useState('')
     const textareaRef = useRef<HTMLTextAreaElement>(null)

     // Auto-resize textarea
     useEffect(() => {
       if (textareaRef.current) {
         textareaRef.current.style.height = 'auto'
         textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`
       }
     }, [input])

     const handleSubmit = () => {
       if (input.trim() && !isLoading) {
         onSend(input.trim())
         setInput('')
       }
     }

     const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
       if (e.key === 'Enter' && !e.shiftKey) {
         e.preventDefault()
         handleSubmit()
       }
     }

     return (
       <div className="border rounded-lg bg-white shadow-sm">
         <div className="flex items-end gap-2 p-3">
           <textarea
             ref={textareaRef}
             value={input}
             onChange={(e) => setInput(e.target.value)}
             onKeyDown={handleKeyDown}
             placeholder={placeholder}
             disabled={isLoading}
             rows={1}
             className={clsx(
               'flex-1 resize-none border-0 focus:ring-0 p-0 text-gray-900 placeholder:text-gray-400',
               'min-h-[24px] max-h-[200px]',
               isLoading && 'opacity-50'
             )}
           />
           <button
             onClick={handleSubmit}
             disabled={!input.trim() || isLoading}
             className={clsx(
               'p-2 rounded-lg transition-colors',
               input.trim() && !isLoading
                 ? 'bg-chiffon-primary text-white hover:bg-chiffon-secondary'
                 : 'bg-gray-100 text-gray-400 cursor-not-allowed'
             )}
           >
             {isLoading ? (
               <Loader2 className="w-5 h-5 animate-spin" />
             ) : (
               <Send className="w-5 h-5" />
             )}
           </button>
         </div>
         <div className="px-3 pb-2 text-xs text-gray-400">
           Press Enter to send, Shift+Enter for new line
         </div>
       </div>
     )
   }
   ```

4. Create frontend/src/components/Chat.tsx:
   ```typescript
   import { useRef, useEffect } from 'react'
   import { useChat } from '../hooks/useChat'
   import ChatMessage from './ChatMessage'
   import ChatInput from './ChatInput'
   import { Loader2 } from 'lucide-react'

   export default function Chat() {
     const { messages, isLoading, error, sendMessage, currentPlan } = useChat()
     const messagesEndRef = useRef<HTMLDivElement>(null)

     // Auto-scroll to bottom on new messages
     useEffect(() => {
       messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
     }, [messages])

     return (
       <div className="flex flex-col h-[600px] bg-gray-50 rounded-xl border">
         {/* Messages area */}
         <div className="flex-1 overflow-y-auto p-4 space-y-4">
           {messages.length === 0 ? (
             <div className="text-center text-gray-500 py-12">
               <p className="text-lg font-medium">Welcome to Chiffon</p>
               <p className="mt-2">
                 Describe what you want to deploy, and I'll create a plan for you.
               </p>
               <p className="mt-4 text-sm">
                 Example: "Deploy Kuma Uptime monitoring to homelab"
               </p>
             </div>
           ) : (
             messages.map((message) => (
               <ChatMessage key={message.id} message={message} />
             ))
           )}

           {isLoading && messages.length > 0 && (
             <div className="flex items-center gap-2 text-gray-500 p-4">
               <Loader2 className="w-4 h-4 animate-spin" />
               <span>Thinking...</span>
             </div>
           )}

           <div ref={messagesEndRef} />
         </div>

         {/* Plan indicator */}
         {currentPlan && (
           <div className="px-4 py-2 bg-chiffon-primary/10 border-t text-sm">
             <span className="font-medium">Active Plan:</span>{' '}
             {currentPlan.summary.slice(0, 50)}...
             <span className="ml-2 text-chiffon-primary">
               [{currentPlan.status}]
             </span>
           </div>
         )}

         {/* Input area */}
         <div className="p-4 border-t bg-white">
           <ChatInput onSend={sendMessage} isLoading={isLoading} />
         </div>
       </div>
     )
   }
   ```

5. Create tests/frontend/Chat.test.tsx:
   ```typescript
   import { describe, it, expect, vi, beforeEach } from 'vitest'
   import { render, screen, fireEvent, waitFor } from '@testing-library/react'
   import Chat from '../../src/components/Chat'
   import * as dashboardModule from '../../src/api/dashboard'

   vi.mock('../../src/api/dashboard')

   describe('Chat', () => {
     beforeEach(() => {
       vi.resetAllMocks()
       vi.mocked(dashboardModule.dashboardApi.createSession).mockResolvedValue({
         session_id: 'test-session',
         user_id: 'test-user',
         created_at: new Date().toISOString(),
         last_activity: new Date().toISOString(),
         messages: [],
         status: 'idle',
       })
     })

     it('renders welcome message when empty', async () => {
       render(<Chat />)
       await waitFor(() => {
         expect(screen.getByText(/Welcome to Chiffon/)).toBeInTheDocument()
       })
     })

     it('displays user message after sending', async () => {
       vi.mocked(dashboardModule.dashboardApi.sendMessage).mockResolvedValue({
         messages: [
           { id: '1', role: 'user', content: 'Deploy Kuma', timestamp: new Date().toISOString() },
           { id: '2', role: 'assistant', content: 'I will create a plan...', timestamp: new Date().toISOString() },
         ],
       })

       render(<Chat />)
       await waitFor(() => screen.getByPlaceholderText(/Describe what you want/))

       const input = screen.getByPlaceholderText(/Describe what you want/)
       fireEvent.change(input, { target: { value: 'Deploy Kuma' } })
       fireEvent.keyDown(input, { key: 'Enter' })

       await waitFor(() => {
         expect(screen.getByText('Deploy Kuma')).toBeInTheDocument()
       })
     })

     it('shows loading indicator while processing', async () => {
       vi.mocked(dashboardModule.dashboardApi.sendMessage).mockImplementation(
         () => new Promise(() => {}) // Never resolves
       )

       render(<Chat />)
       await waitFor(() => screen.getByPlaceholderText(/Describe what you want/))

       const input = screen.getByPlaceholderText(/Describe what you want/)
       fireEvent.change(input, { target: { value: 'Deploy Kuma' } })
       fireEvent.keyDown(input, { key: 'Enter' })

       await waitFor(() => {
         expect(screen.getByText('Thinking...')).toBeInTheDocument()
       })
     })

     it('displays error message on API failure', async () => {
       vi.mocked(dashboardModule.dashboardApi.sendMessage).mockRejectedValue({
         detail: 'Network error',
         status: 500,
       })

       render(<Chat />)
       await waitFor(() => screen.getByPlaceholderText(/Describe what you want/))

       const input = screen.getByPlaceholderText(/Describe what you want/)
       fireEvent.change(input, { target: { value: 'Deploy Kuma' } })
       fireEvent.keyDown(input, { key: 'Enter' })

       await waitFor(() => {
         expect(screen.getByText(/Error: Network error/)).toBeInTheDocument()
       })
     })
   })
   ```
  </action>
  <verify>
    - [ ] Chat component renders with welcome message
    - [ ] Messages display correctly (user vs assistant)
    - [ ] Input accepts text and sends on Enter
    - [ ] Loading state shows "Thinking..."
    - [ ] Errors display as system messages
    - [ ] Tests pass: `cd frontend && npm test`
  </verify>
  <done>Chat interface components and hook created with full test coverage</done>
</task>

</tasks>

<verification>
After all tasks complete:
1. Install frontend: `cd frontend && npm install`
2. Start dev server: `npm run dev`
3. Visit http://localhost:3000
4. Type "Deploy Kuma" and press Enter (will fail without backend, but UI works)
5. Run tests: `npm test`
</verification>

<success_criteria>
- Frontend builds without errors
- Chat interface renders with welcome message
- User can type deployment request and submit
- Messages display in conversation format
- Loading states shown during processing
- Error states displayed clearly
- All tests pass (target: 10+ test cases)
- UI responsive and accessible
</success_criteria>

<output>
After completion, create `.planning/phases/07-user-interface/07-03-SUMMARY.md`
</output>
