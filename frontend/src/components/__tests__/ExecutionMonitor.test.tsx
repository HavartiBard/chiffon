import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import ExecutionMonitor from '../ExecutionMonitor'
import { useExecution } from '../../hooks/useExecution'
import type { PlanView } from '../../types/dashboard'

vi.mock('../../hooks/useExecution')
const mockedUseExecution = vi.mocked(useExecution)

const basePlan: PlanView = {
  planId: 'plan-1',
  requestId: 'request-1',
  summary: 'Deploy Kuma',
  steps: [
    { index: 0, name: 'Prepare', description: 'Prepare', status: 'pending' },
    { index: 1, name: 'Deploy', description: 'Deploy', status: 'pending' },
  ],
  estimatedDuration: '~2 minutes',
  riskLevel: 'low',
  resourceRequirements: {},
  status: 'pending_approval',
  canApprove: true,
  canModify: true,
  canAbort: true,
}

const noop = vi.fn()

beforeEach(() => {
  vi.resetAllMocks()
  Object.defineProperty(globalThis, 'navigator', {
    value: {
      clipboard: {
        writeText: vi.fn(),
      },
    },
    configurable: true,
  })
})

function mockExecution(stateOverrides = {}) {
  const state = {
    plan: basePlan,
    steps: basePlan.steps,
    stepOutputs: {},
    isExecuting: true,
    isCompleted: false,
    isFailed: false,
    isAborting: false,
    summary: null,
    error: null,
    fallbackPolling: false,
    startExecution: vi.fn(),
    abort: vi.fn(),
    clearExecution: vi.fn(),
    pollPlanNow: vi.fn(),
    ...stateOverrides,
  }
  mockedUseExecution.mockReturnValue(state)
  return state
}

describe('ExecutionMonitor', () => {
  it('renders execution steps and progress', () => {
    const executionState = mockExecution()
    render(<ExecutionMonitor plan={basePlan} sessionId="session-1" onComplete={noop} />)

    expect(screen.getByText('Executing Plan')).toBeInTheDocument()
    expect(screen.getByText('Prepare')).toBeInTheDocument()
    expect(screen.getByText('Deploy')).toBeInTheDocument()
    expect(screen.getByText('Copy execution logs')).toBeInTheDocument()
    expect(executionState.startExecution).toHaveBeenCalled()
  })

  it('shows abort button when executing', () => {
    mockExecution({ isAborting: false })
    render(<ExecutionMonitor plan={basePlan} sessionId="session-1" onComplete={noop} />)

    expect(screen.getByRole('button', { name: /Abort/i })).toBeInTheDocument()
  })

  it('shows fallback polling hint when necessary', () => {
    mockExecution({ fallbackPolling: true })
    render(<ExecutionMonitor plan={basePlan} sessionId="session-1" onComplete={noop} />)

    expect(screen.getByText(/falling back to polling/i)).toBeInTheDocument()
  })

  it('shows error banner when execution fails', () => {
    mockExecution({ error: 'Something broke' })
    render(<ExecutionMonitor plan={basePlan} sessionId="session-1" onComplete={noop} />)

    expect(screen.getByText('Something broke')).toBeInTheDocument()
  })

  it('renders summary after completion', () => {
    const summary = {
      total_duration_ms: 120000,
      steps_completed: 2,
      steps_failed: 0,
      resources_used: { cpu: '2 cores' },
      audit_trail_url: 'https://example.com/audit',
    }
    const onComplete = vi.fn()
    mockExecution({
      isExecuting: false,
      isCompleted: true,
      summary,
      stepOutputs: { 0: ['ok'], 1: ['done'] },
    })

    render(<ExecutionMonitor plan={basePlan} sessionId="session-1" onComplete={onComplete} />)

    expect(screen.getByText('Execution Completed')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Start New Request/i }))
    expect(onComplete).toHaveBeenCalled()
  })

  it('copies logs when button clicked', async () => {
    mockExecution({
      stepOutputs: { 0: ['foo'], 1: ['bar'] },
    })
    render(<ExecutionMonitor plan={basePlan} sessionId="session-1" onComplete={noop} />)

    fireEvent.click(screen.getByRole('button', { name: /Copy execution logs/i }))
    await waitFor(() =>
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith('foo\nbar')
    )
  })
})
