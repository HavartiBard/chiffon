import { useEffect, useMemo, useRef, useState } from 'react'
import { useChat } from '../hooks/useChat'

export default function ChatInterface() {
  const { messages, sendMessage, isLoading, error, plan } = useChat()
  const [draft, setDraft] = useState('')
  const containerRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    containerRef.current?.scrollTo({ top: containerRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  const handleSubmit = () => {
    if (!draft.trim() || isLoading) return
    sendMessage(draft.trim())
    setDraft('')
  }

  const buttonLabel = useMemo(() => (isLoading ? 'Sending...' : 'Send'), [isLoading])

  return (
    <div className="flex flex-col rounded-xl border bg-white shadow-sm h-full">
      <div className="border-b px-5 py-4 text-lg font-semibold text-gray-900">Deployment Chat</div>
      <div ref={containerRef} className="flex-1 space-y-4 overflow-y-auto p-5">
        {messages.length === 0 ? (
          <div className="space-y-2 text-center text-sm text-gray-500">
            <p className="text-base font-semibold">Welcome to Chiffon</p>
            <p>Describe what you want to deploy and I will craft a plan.</p>
          </div>
        ) : (
          messages.map((message) => (
            <div
              key={message.id}
              className={`rounded-xl px-4 py-3 shadow-sm ${
                message.role === 'user'
                  ? 'bg-chiffon-primary/10 text-chiffon-primary'
                  : 'bg-gray-50 text-gray-900'
              }`}
            >
              <div className="text-xs uppercase tracking-wide text-gray-500">
                {message.role === 'user' ? 'You' : message.role === 'assistant' ? 'Chiffon' : 'System'}
              </div>
              <p className="mt-1 text-sm leading-relaxed">{message.content}</p>
            </div>
          ))
        )}
        {plan && (
          <div className="rounded-xl border border-chiffon-primary/30 bg-chiffon-primary/5 p-3 text-sm text-chiffon-primary">
            Active plan ready: {plan.summary}
          </div>
        )}
      </div>
      {error && <div className="px-5 text-sm text-red-600">{error}</div>}
      <div className="border-t px-5 py-4 bg-gray-50">
        <div className="flex gap-3">
          <textarea
            className="flex-1 resize-none rounded-2xl border border-gray-200 bg-white px-4 py-3 text-sm leading-relaxed shadow-inner focus:border-chiffon-primary focus:outline-none"
            placeholder="Describe your deployment request..."
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                handleSubmit()
              }
            }}
            disabled={isLoading}
            rows={2}
          />
          <button
            className="flex-shrink-0 rounded-2xl bg-chiffon-primary px-5 py-3 text-sm font-semibold text-white hover:bg-chiffon-secondary disabled:cursor-not-allowed disabled:opacity-60"
            onClick={handleSubmit}
            disabled={!draft.trim() || isLoading}
          >
            {buttonLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
