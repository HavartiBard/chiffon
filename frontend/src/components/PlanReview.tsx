import type { PlanView } from '../types/dashboard'

interface PlanReviewProps {
  plan: PlanView
}

const statusColors: Record<string, string> = {
  pending: 'bg-gray-100 text-gray-700',
  running: 'bg-blue-50 text-blue-700',
  completed: 'bg-green-50 text-green-800',
  failed: 'bg-red-50 text-red-700',
}

export default function PlanReview({ plan }: PlanReviewProps) {
  return (
    <div className="rounded-xl border bg-white shadow-sm">
      <div className="space-y-2 border-b px-6 py-5">
        <h2 className="text-xl font-semibold text-gray-900">Execution Plan</h2>
        <p className="text-sm text-gray-600">{plan.summary}</p>
        <div className="flex flex-wrap gap-3 text-xs font-medium text-gray-600">
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-full bg-green-500" /> {plan.estimatedDuration}
          </span>
          <span
            className={`rounded-full px-3 py-1 text-[11px] uppercase tracking-wide ${
              plan.riskLevel === 'low'
                ? 'bg-green-100 text-green-700'
                : plan.riskLevel === 'medium'
                ? 'bg-yellow-100 text-yellow-700'
                : 'bg-red-100 text-red-700'
            }`}
          >
            {plan.riskLevel} risk
          </span>
          <span>{plan.steps.length} steps</span>
        </div>
      </div>
      <div className="space-y-3 p-6">
        {plan.steps.map((step) => (
          <div key={step.index} className="rounded-xl border p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-sm font-semibold text-gray-900">{step.name}</p>
                <p className="text-xs text-gray-500">{step.description}</p>
              </div>
              <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold capitalize ${statusColors[step.status] || statusColors.pending}`}>
                {step.status}
              </span>
            </div>
            {step.metadata && (
              <div className="mt-3 text-xs text-gray-400">
                {Object.entries(step.metadata).map(([key, value]) => (
                  <span key={key} className="inline-flex items-center gap-1 border-r pr-2 last:border-none last:pr-0">
                    <strong className="text-gray-600">{key}:</strong> {String(value)}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
      {Boolean(Object.keys(plan.resourceRequirements).length) && (
        <div className="border-t px-6 py-4">
          <h3 className="text-sm font-semibold text-gray-900">Resources</h3>
          <dl className="mt-2 grid grid-cols-2 gap-4 text-xs text-gray-600">
            {Object.entries(plan.resourceRequirements).map(([key, value]) => (
              <div key={key}>
                <dt className="font-medium text-gray-500">{key}</dt>
                <dd>{String(value)}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </div>
  )
}
