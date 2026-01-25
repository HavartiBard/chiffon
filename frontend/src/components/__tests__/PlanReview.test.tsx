import { render, screen } from '@testing-library/react'
import PlanReview from '../PlanReview'
import type { PlanView } from '../../types/dashboard'

const plan: PlanView = {
  planId: 'plan-1',
  requestId: 'req-1',
  summary: 'Deploy Kuma',
  steps: [
    { index: 0, name: 'Step One', description: 'First', status: 'pending' },
    { index: 1, name: 'Step Two', description: 'Second', status: 'completed', metadata: { order: 2 } },
  ],
  estimatedDuration: '~5 minutes',
  riskLevel: 'low',
  resourceRequirements: { cpu: '2 cores' },
  status: 'pending',
  canApprove: true,
  canModify: true,
  canAbort: false,
}

describe('PlanReview', () => {
  it('renders summary and meta', () => {
    render(<PlanReview plan={plan} />)
    expect(screen.getByText('Deploy Kuma')).toBeInTheDocument()
    expect(screen.getByText('~5 minutes')).toBeInTheDocument()
    expect(screen.getByText(/low risk/i)).toBeInTheDocument()
  })

  it('renders steps list', () => {
    render(<PlanReview plan={plan} />)
    expect(screen.getByText('Step One')).toBeInTheDocument()
    expect(screen.getByText('Step Two')).toBeInTheDocument()
  })

  it('shows resource requirements', () => {
    render(<PlanReview plan={plan} />)
    expect(screen.getByText('Resources')).toBeInTheDocument()
    expect(screen.getByText('cpu:')).toBeInTheDocument()
  })
})
