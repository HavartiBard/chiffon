import { useCallback, useEffect, useRef, useState } from 'react'
import { io, Socket } from 'socket.io-client'
import type { PlanEventPayload } from '../types/dashboard'

const SOCKET_PATH = '/ws/socket.io'

interface UseWebSocketOptions {
  sessionId: string
  onPlanEvent?: (payload: PlanEventPayload) => void
  onError?: (message: string) => void
}

interface UseWebSocketReturn {
  isConnected: boolean
  isConnecting: boolean
  error: string | null
  subscribe: (planId: string, metadata?: { requestId?: string; executionId?: string }) => void
  unsubscribe: (planId: string) => void
  reconnect: () => void
}

const createId = (): string => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `sub-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function useWebSocket({
  sessionId,
  onPlanEvent,
  onError,
}: UseWebSocketOptions): UseWebSocketReturn {
  const [isConnected, setIsConnected] = useState(false)
  const [isConnecting, setIsConnecting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const socketRef = useRef<Socket | null>(null)
  const subscriptionsRef = useRef<Record<string, string>>({})

  const disconnect = useCallback(() => {
    const socket = socketRef.current
    if (socket) {
      socket.off()
      socket.disconnect()
    }
    socketRef.current = null
    setIsConnected(false)
  }, [])

  const connect = useCallback(() => {
    if (socketRef.current?.connected) {
      return
    }

    setIsConnecting(true)
    const protocol = typeof window !== 'undefined' && window.location.protocol === 'https:' ? 'https:' : 'http:'
    const host = typeof window !== 'undefined' ? window.location.host : 'localhost:8001'
    const url = `${protocol}//${host}`

    const socket = io(url, {
      path: SOCKET_PATH,
      transports: ['websocket'],
      autoConnect: true,
      withCredentials: true,
      query: {
        session_id: sessionId,
      },
    })

    socketRef.current = socket

    socket.on('connect', () => {
      setIsConnected(true)
      setIsConnecting(false)
      setError(null)
    })

    socket.on('disconnect', () => {
      setIsConnected(false)
      setIsConnecting(false)
    })

    socket.on('connect_error', (connError: Error) => {
      const message = connError?.message || 'WebSocket connection failed'
      setError(message)
      onError?.(message)
      setIsConnecting(false)
    })

    socket.on('error', (payload: { message?: string }) => {
      const message = payload?.message ?? 'WebSocket error'
      setError(message)
      onError?.(message)
    })

    socket.on('plan_event', (payload: PlanEventPayload) => {
      onPlanEvent?.(payload)
    })

    socket.on('subscription_ack', () => {
      // optional ack handling
    })

    socket.on('unsubscribed', () => {
      // optional ack handling
    })
  }, [onError, onPlanEvent, sessionId])

  useEffect(() => {
    connect()
    return () => {
      disconnect()
    }
  }, [connect, disconnect])

  const subscribe = useCallback(
    (planId: string, metadata?: { requestId?: string; executionId?: string }) => {
      if (!planId || !socketRef.current?.connected) {
        return
      }
      const subscriptionId = createId()
      subscriptionsRef.current[planId] = subscriptionId
      socketRef.current.emit(
        'subscribe',
        {
          plan_id: planId,
          subscription_id: subscriptionId,
          session_id: sessionId,
          request_id: metadata?.requestId,
          execution_id: metadata?.executionId,
        },
        (ack: { subscription_id: string }) => {
          if (ack?.subscription_id) {
            subscriptionsRef.current[planId] = ack.subscription_id
          }
        }
      )
    },
    [sessionId]
  )

  const unsubscribe = useCallback(
    (planId: string) => {
      if (!planId || !socketRef.current) {
        return
      }
      const subscriptionId = subscriptionsRef.current[planId]
      const payload = subscriptionId
        ? { subscription_id: subscriptionId }
        : { plan_id: planId }
      socketRef.current.emit('unsubscribe', payload)
      delete subscriptionsRef.current[planId]
    },
    []
  )

  const reconnect = useCallback(() => {
    disconnect()
    connect()
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
