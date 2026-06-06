import type { DisplayPlan } from '../types'
import { PlanCard } from './PlanCard'

interface Props {
  plans: DisplayPlan[]
  acceptedAlternatives?: Set<string>
  selectedAddonsByPlan?: Map<string, Set<string>>
  onConfirm: (planId: string, selectedAddonIds: string[]) => void
  onToggleAddon?: (planId: string, addonId: string, checked: boolean) => void
  onEditPreference: () => void
  onAcceptAlternative?: (planId: string) => void
  onReject: () => void
  disabled?: boolean
}

export function PlanCards({
  plans,
  acceptedAlternatives,
  selectedAddonsByPlan,
  onConfirm,
  onToggleAddon,
  onEditPreference,
  onAcceptAlternative,
  onReject,
  disabled,
}: Props) {
  return (
    <div className="plan-cards">
      <div className="plan-cards-scroll">
        {plans.map((plan, index) => (
          <PlanCard
            key={plan.id}
            plan={plan}
            isTop1={index === 0}
            alternativeAccepted={acceptedAlternatives?.has(plan.id)}
            selectedAddonIds={selectedAddonsByPlan?.get(plan.id)}
            onConfirm={onConfirm}
            onToggleAddon={onToggleAddon}
            onEditPreference={onEditPreference}
            onAcceptAlternative={onAcceptAlternative}
            disabled={disabled}
          />
        ))}
      </div>
      <button
        type="button"
        className="reject-btn"
        onClick={onReject}
        disabled={disabled}
      >
        都不喜欢，补充偏好重新规划
      </button>
    </div>
  )
}
