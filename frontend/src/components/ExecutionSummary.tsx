import { useMemo, useState } from 'react'
import { clsx } from 'clsx'
import {
  CheckCircle,
  Clock,
  Cpu,
  ExternalLink,
  FileText,
  XCircle,
} from 'lucide-react'
import type { ExecutionSummaryPayload } from '../types/dashboard'

interface ExecutionSummaryProps {
  summary: ExecutionSummaryPayload
  logs?: string[]
  onClose: () => void
}

export default function ExecutionSummary({ summary, logs = [], onClose }: ExecutionSummaryProps) {
  const isSuccess = summary.steps_failed === 0
  const [showLogs, setShowLogs] = useState(false)

  const formattedDuration = useMemo(() => {
    if (!summary.total_duration_ms) {
      return 'Unknown duration'
    }
    return `${(summary.total_duration_ms / 1000).toFixed(1)}s`
  }, [summary.total_duration_ms])

  const resourceEntries = useMemo(
    () => Object.entries(summary.resources_used || {}),
    [summary.resources_used]
  )

  const copyAuditTrail = async () => {
    if (!summary.audit_trail_url) return
    try {
      await navigator.clipboard.writeText(summary.audit_trail_url)
    } catch {
      // ignore
    }
  }

  return (
    <div className="rounded-xl border bg-white shadow-sm">
      <div
        className={clsx(
          'flex items-center gap-4 border-b p-6',
          isSuccess ? 'bg-green-50' : 'bg-red-50'
        )}
      >
        {isSuccess ? (
          <CheckCircle className="h-10 w-10 text-green-500" />
        ) : (
          <XCircle className="h-10 w-10 text-red-500" />
        )}
        <div>
          <h2 className="text-xl font-semibold text-gray-900">
            {isSuccess ? 'Execution Completed' : 'Execution Failed'}
          </h2>
          <p className="text-sm text-gray-600">
            {summary.steps_completed} of {summary.steps_completed + summary.steps_failed} steps completed
          </p>
        </div>
      </div>

      <div className="grid gap-4 border-b p-6 text-sm text-gray-600 md:grid-cols-2">
        <div className="rounded-xl border bg-gray-50 p-4">
          <div className="flex items-center gap-2 text-gray-500">
            <Clock className="h-4 w-4" />
            Duration
          </div>
          <p className="mt-2 text-xl font-semibold text-gray-900">{formattedDuration}</p>
        </div>
        <div className="rounded-xl border bg-gray-50 p-4">
          <div className="flex items-center gap-2 text-gray-500">
            <Cpu className="h-4 w-4" />
            Resources
          </div>
          <div className="mt-2 text-sm text-gray-800">
            {resourceEntries.length > 0 ? (
              resourceEntries.map(([key, value]) => (
                <div key={key}>
                  <span className="font-semibold">{key}:</span> {String(value)}
                </div>
              ))
            ) : (
              <div className="text-xs text-gray-400">No resource data</div>
            )}
          </div>
        </div>
        <div className="rounded-xl border bg-gray-50 p-4">
          <div className="flex items-center gap-2 text-gray-500">
            <CheckCircle className="h-4 w-4 text-green-500" />
            Completed
          </div>
          <p className="mt-2 text-2xl font-semibold text-green-600">{summary.steps_completed}</p>
        </div>
        <div className="rounded-xl border bg-gray-50 p-4">
          <div className="flex items-center gap-2 text-gray-500">
            <XCircle className="h-4 w-4 text-red-500" />
            Failed
          </div>
          <p className="mt-2 text-2xl font-semibold text-red-600">{summary.steps_failed}</p>
        </div>
      </div>

      <div className="space-y-4 p-6">
        {summary.audit_trail_url && (
          <a
            href={summary.audit_trail_url}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-2 text-chiffon-primary hover:underline"
          >
            <FileText className="h-4 w-4" />
            View Audit Trail
            <ExternalLink className="h-3 w-3" />
          </a>
        )}

        {summary.postgres_record_url && (
          <a
            href={summary.postgres_record_url}
            target="_blank"
            rel="noreferrer"
            className="text-sm text-gray-600 hover:underline"
          >
            Task record
          </a>
        )}

        {summary.task_ids && summary.task_ids.length > 0 && (
          <div className="text-sm text-gray-600">
            Task IDs: {summary.task_ids.join(', ')}
          </div>
        )}

        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={() => setShowLogs((prev) => !prev)}
            className="flex items-center gap-2 rounded-lg bg-gray-100 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-gray-600 transition hover:bg-gray-200"
          >
            {showLogs ? 'Hide Logs' : 'View Full Logs'}
          </button>
          {summary.audit_trail_url && (
            <button
              onClick={copyAuditTrail}
              className="flex items-center gap-2 rounded-lg bg-chiffon-primary px-4 py-2 text-xs font-semibold uppercase tracking-wide text-white transition hover:bg-chiffon-secondary"
            >
              Share Audit Trail
            </button>
          )}
        </div>

        {showLogs && logs.length > 0 && (
          <div className="rounded-lg border border-gray-200 bg-gray-900 p-4 text-[11px] font-mono text-white">
            <pre className="max-h-52 overflow-y-auto whitespace-pre-wrap">
              {logs.join('\n')}
            </pre>
          </div>
        )}
      </div>

      <div className="flex justify-end border-t p-6">
        <button
          onClick={onClose}
          className="rounded-lg bg-chiffon-primary px-5 py-2 text-sm font-semibold text-white transition hover:bg-chiffon-secondary"
        >
          Start New Request
        </button>
      </div>
    </div>
  )
}
