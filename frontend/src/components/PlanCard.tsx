import type { DisplayPlan } from '../types'

interface Props {
  plan: DisplayPlan
  isTop1?: boolean
  alternativeAccepted?: boolean
  selectedAddonIds?: Set<string>
  onConfirm: (planId: string, selectedAddonIds: string[]) => void
  onToggleAddon?: (planId: string, addonId: string, checked: boolean) => void
  onEditPreference: () => void
  onAcceptAlternative?: (planId: string) => void
  disabled?: boolean
}

export function PlanCard({
  plan,
  isTop1,
  alternativeAccepted,
  selectedAddonIds,
  onConfirm,
  onToggleAddon,
  onEditPreference,
  onAcceptAlternative,
  disabled,
}: Props) {
  const canOrder =
    plan.isValid || (plan.issueKind === 'alternative_available' && alternativeAccepted)
  const confirmDisabled = disabled || !canOrder
  const showIssuePanel = plan.planIssues.length > 0 && !canOrder

  const badgeLabel =
    plan.issueKind === 'needs_preference_fix'
      ? '等你调整'
      : plan.issueKind === 'alternative_available'
        ? '附近暂无'
        : '正在换方案'

  const issuePanelClass =
    plan.issueKind === 'needs_preference_fix'
      ? 'plan-issue-panel plan-issue-panel-warn'
      : plan.issueKind === 'alternative_available'
        ? 'plan-issue-panel plan-issue-panel-info'
        : 'plan-issue-panel plan-issue-panel-error'

  return (
    <div className={`plan-card ${canOrder ? '' : 'plan-card-invalid'}`}>
      <div className="plan-card-header">
        <span className="plan-card-title">{plan.venueChain}</span>
        <span className="plan-card-subtitle">{plan.diffSummary}</span>
        {isTop1 && canOrder && <div className="badge-recommend">推荐</div>}
        {!canOrder && <div className="badge-invalid">{badgeLabel}</div>}
      </div>

      {plan.activeConstraints.length > 0 && (
        <div className="plan-active-constraints">
          <div className="plan-active-constraints-label">我会重点照顾</div>
          <div className="plan-active-constraints-tags">
            {plan.activeConstraints.map((c, i) => (
              <span key={`${c}-${i}`} className="active-constraint-tag">{c}</span>
            ))}
          </div>
        </div>
      )}

      {showIssuePanel && (
        <div className={issuePanelClass}>
          {plan.planIssues.map((issue, i) => (
            <div key={i} className="plan-issue-block">
              <div className="plan-issue-label">{issue.headline}</div>
              <div className="plan-issue-item">{issue.detail}</div>
              {issue.suggestions && issue.suggestions.length > 0 && (
                <ul className="plan-issue-suggestions">
                  {issue.suggestions.map((s, j) => (
                    <li key={j}>{s}</li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}

      {plan.issueKind === 'alternative_available' && alternativeAccepted && (
        <div className="plan-issue-panel plan-issue-panel-accepted">
          <div className="plan-issue-label">好的，已按就近替代方案继续，可以下单</div>
        </div>
      )}

      {plan.matchReasons.length > 0 && (
        <div className="plan-match-reasons">
          <div className="plan-match-label">为什么推荐这条路线</div>
          <div className="plan-match-tags">
            {plan.matchReasons.map((r, i) => (
              <span key={i} className="match-tag">{r}</span>
            ))}
          </div>
        </div>
      )}

      <div className="plan-timeline">
        {plan.timeline.map((item, index) => (
          <div key={`${item.kind}-${index}`}>
            {index > 0 && (
              <div className={`timeline-connector ${item.kind === 'addon' ? 'dashed' : ''}`} />
            )}
            <TimelineItem item={item} />
          </div>
        ))}
      </div>

      <div className="plan-card-footer">
        <span className="plan-price">{plan.totalPrice}</span>
      </div>

      {plan.addons && plan.addons.length > 0 && canOrder && (
        <div className="plan-addons-section">
          <div className="plan-addons-label">智能附加建议（顺路/送到店）</div>
          {plan.addons.map((addon) => {
            const checked = selectedAddonIds?.has(addon.addon_id) ?? true
            return (
              <label key={addon.addon_id} className="plan-addon-item">
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={(e) =>
                    onToggleAddon?.(plan.id, addon.addon_id, e.target.checked)
                  }
                  disabled={disabled}
                />
                <span>
                  {addon.description} (¥{addon.price})
                </span>
              </label>
            )
          })}
        </div>
      )}

      <div className="plan-card-actions">
        {plan.issueKind === 'alternative_available' && !alternativeAccepted && (
          <button
            type="button"
            className="btn-primary"
            onClick={() => onAcceptAlternative?.(plan.id)}
            disabled={disabled}
          >
            接受这个替代
          </button>
        )}
        <button
          type="button"
          className={
            plan.issueKind === 'needs_preference_fix' ? 'btn-primary' : 'btn-secondary'
          }
          onClick={onEditPreference}
          disabled={disabled}
        >
          {plan.issueKind === 'needs_preference_fix' ? '调整一下偏好' : '换个偏好再试'}
        </button>
        <button
          type="button"
          className={
            plan.issueKind === 'alternative_available' && !alternativeAccepted
              ? 'btn-secondary'
              : 'btn-primary'
          }
          onClick={() =>
            onConfirm(
              plan.id,
              plan.addons
                ?.filter((a) => (selectedAddonIds?.has(a.addon_id) ?? true))
                .map((a) => a.addon_id) ?? [],
            )
          }
          disabled={confirmDisabled}
        >
          {canOrder
            ? '就选这个，帮我下单'
            : plan.issueKind === 'needs_preference_fix'
              ? '先调一下偏好'
              : plan.issueKind === 'alternative_available'
                ? '先确认替代'
                : '正在换更合适的方案'}
        </button>
      </div>
    </div>
  )
}

function TimelineItem({
  item,
}: {
  item: DisplayPlan['timeline'][number]
}) {
  return (
    <div className={`timeline-item ${item.kind === 'addon' ? 'addon' : ''}`}>
      <div className="timeline-dot">
        <span className="timeline-kind">{item.label}</span>
      </div>
      <div className="timeline-content">
        <div className="timeline-time">{item.time}</div>
        <div className="timeline-name">{item.name}</div>
        <div className="timeline-desc">{item.desc}</div>
        {(item.priceLabel || item.distanceLabel) && (
          <div className="timeline-meta">
            {[item.priceLabel, item.distanceLabel].filter(Boolean).join(' · ')}
          </div>
        )}
        <div className="timeline-tags">
          {item.tags.map((t, i) => (
            <span key={i} className="tag">{t}</span>
          ))}
        </div>
      </div>
    </div>
  )
}
