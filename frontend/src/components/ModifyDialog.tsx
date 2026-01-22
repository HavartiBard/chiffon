import { useEffect, useRef, useState } from 'react'

interface ModifyDialogProps {
  isOpen: boolean
  onClose: () => void
  onSubmit: (modification: string) => Promise<void>
  isLoading?: boolean
}

export default function ModifyDialog({ isOpen, onClose, onSubmit, isLoading = false }: ModifyDialogProps) {
  const [text, setText] = useState('')
  const areaRef = useRef<HTMLTextAreaElement | null>(null)

  useEffect(() => {
    if (isOpen) {
      areaRef.current?.focus()
    } else {
      setText('')
    }
  }, [isOpen])

  if (!isOpen) return null

  const handleSubmit = async () => {
    if (!text.trim()) return
    await onSubmit(text.trim())
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4">
      <div className="relative w-full max-w-xl rounded-2xl bg-white p-6">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-semibold text-gray-900">Request Plan Changes</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            ×
          </button>
        </div>
        <p className="mt-2 text-sm text-gray-600">
          Describe the adaptation you want. Examples: add staging, skip DNS, include a backup step.
        </p>
        <textarea
          ref={areaRef}
          value={text}
          onChange={(event) => setText(event.target.value)}
          rows={4}
          className="mt-4 w-full rounded-xl border border-gray-200 px-4 py-3 text-sm focus:border-chiffon-primary focus:outline-none"
          placeholder="I want to run this in staging before prod..."
          disabled={isLoading}
        />
        <div className="mt-4 flex justify-end gap-3">
          <button
            className="rounded-xl border border-gray-200 px-4 py-2 text-sm font-semibold text-gray-600"
            onClick={onClose}
            disabled={isLoading}
          >
            Cancel
          </button>
          <button
            className="rounded-xl bg-chiffon-primary px-4 py-2 text-sm font-semibold text-white hover:bg-chiffon-secondary disabled:opacity-50"
            onClick={handleSubmit}
            disabled={!text.trim() || isLoading}
          >
            {isLoading ? 'Submitting...' : 'Submit Changes'}
          </button>
        </div>
      </div>
    </div>
  )
}
