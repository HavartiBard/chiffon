import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import ApprovalControls from '../ApprovalControls'

const makeProps = () => ({
  planId: 'plan-1',
  sessionId: 'session-1',
  onApprove: vi.fn(async () => {}),
  onReject: vi.fn(async () => {}),
  onModify: vi.fn(async () => {}),
  isApproving: false,
  isRejecting: false,
  isModifying: false,
})

describe('ApprovalControls', () => {
  it('calls approve and reject', async () => {
    const props = makeProps()
    render(<ApprovalControls {...props} />)

    fireEvent.click(screen.getByText(/Approve & Execute/i))
    fireEvent.click(screen.getByText(/Reject/i))

    expect(props.onApprove).toHaveBeenCalled()
    expect(props.onReject).toHaveBeenCalled()
  })

  it('shows modify dialog and submits', async () => {
    const props = makeProps()
    render(<ApprovalControls {...props} />)

    fireEvent.click(screen.getByText(/Request Changes/i))
    expect(screen.getByPlaceholderText(/I want to run this in staging/i)).toBeInTheDocument()

    fireEvent.change(screen.getByPlaceholderText(/I want to run this in staging/i), {
      target: { value: 'Use staging first' },
    })
    fireEvent.click(screen.getByText(/Submit Changes/i))

    await waitFor(() => {
      expect(props.onModify).toHaveBeenCalledWith('Use staging first')
    })
  })
})
