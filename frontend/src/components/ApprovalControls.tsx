import { useMemo, useState } from 'react'
import ModifyDialog from './ModifyDialog'

interface ApprovalControlsProps {
  planId: string
  sessionId: string
  isApproving?: boolean
  isRejecting?: boolean
  isModifying?: boolean
  onApprove: () => Promise<void>
  onReject: () => Promise<void>
  onModify: (modification: string) => Promise<void>
}

export default function ApprovalControls({
  planId,
  sessionId,
  onApprove,
  onReject,
  onModify,
  isApproving = false,
  isRejecting = false,
  isModifying = false,
}: ApprovalControlsProps) {
  const [showDialog, setShowDialog] = useState(false)
  const busy = isApproving || isRejecting || isModifying

  const approveLabel = useMemo(() => (isApproving ? 'Approving...' : 'Approve & Execute'), [isApproving])
  const rejectLabel = useMemo(() => (isRejecting ? 'Rejecting...' : 'Reject'), [isRejecting])

  const handleApprove = async () => {
    await onApprove()
  }

  const handleReject = async () => {
    await onReject()
  }

  const handleModify = async (text: string) => {
    await onModify(text)
    setShowDialog(false)
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-3 sm:flex-row">
        <button
          className="flex-1 rounded-2xl bg-green-600 px-4 py-3 text-sm font-semibold text-white hover:bg-green-700 disabled:cursor-not-allowed disabled:opacity-60"
          onClick={handleApprove}
          disabled={busy}
        >
          {approveLabel}
        </button>
        <button
          className="flex-1 rounded-2xl border border-red-300 px-4 py-3 text-sm font-semibold text-red-600 hover:border-red-500 disabled:cursor-not-allowed disabled:opacity-60"
          onClick={handleReject}
          disabled={busy}
        >
          {rejectLabel}
        </button>
        <button
          className="flex-1 rounded-2xl border border-chiffon-primary/30 bg-chiffon-primary/10 px-4 py-3 text-sm font-semibold text-chiffon-primary hover:bg-chiffon-primary/20 disabled:cursor-not-allowed disabled:opacity-60"
          onClick={() => setShowDialog(true)}
          disabled={busy}
        >
          {isModifying ? 'Requesting changes...' : 'Request Changes'}
        </button>
      </div>
      <ModifyDialog
        isOpen={showDialog}
        onClose={() => setShowDialog(false)}
        onSubmit={handleModify}
        isLoading={isModifying}
      />
      <p className="text-xs text-gray-500">Plan ID: {planId}</p>
    </div>
  )
}
