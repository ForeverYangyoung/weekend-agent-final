import type { DisplayPlan } from '../types'
import { PlanCard } from './PlanCard'

interface Props {
  plans: DisplayPlan[]
  onConfirm: (planId: string) => void
  onReject: () => void
  onModify?: (planId: string) => void
  onSubmitFeedback?: (planId: string, feedback: string) => void
  onCancelModify?: () => void
  feedbackPlanId?: string | null
  revisionLoading?: boolean
  disabled?: boolean
}

export function PlanCards({
  plans,
  onConfirm,
  onReject,
  onModify,
  onSubmitFeedback,
  onCancelModify,
  feedbackPlanId,
  revisionLoading,
  disabled,
}: Props) {
  return (
    <div className="plan-cards">
      <div className="plan-cards-scroll">
        {plans.map((plan) => (
          <PlanCard
            key={plan.id}
            plan={plan}
            onConfirm={onConfirm}
            onModify={onModify}
            onSubmitFeedback={onSubmitFeedback}
            onCancelModify={onCancelModify}
            isModifying={feedbackPlanId === plan.id}
            revisionLoading={revisionLoading}
            disabled={disabled}
          />
        ))}
      </div>
      <button
        className="reject-btn"
        onClick={onReject}
        disabled={disabled}
      >
        都不喜欢，补充偏好重新规划
      </button>
    </div>
  )
}
