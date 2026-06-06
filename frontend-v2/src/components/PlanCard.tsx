import { useState } from 'react'
import type { DisplayPlan, DisplayStage, DisplayTransit } from '../types'

interface Props {
  plan: DisplayPlan
  onConfirm: (planId: string) => void
  onModify?: (planId: string) => void
  onSubmitFeedback?: (planId: string, feedback: string) => void
  onCancelModify?: () => void
  isModifying?: boolean
  revisionLoading?: boolean
  disabled?: boolean
}

const QUICK_CHIPS = [
  { label: '换个餐厅', text: '餐厅换一个' },
  { label: '换个活动', text: '活动换一个' },
  { label: '顺路买奶茶', text: '顺路买杯奶茶' },
  { label: '不要加餐', text: '不要加餐了' },
]

export function PlanCard({
  plan,
  onConfirm,
  onModify,
  onSubmitFeedback,
  onCancelModify,
  isModifying,
  revisionLoading,
  disabled,
}: Props) {
  const [feedbackText, setFeedbackText] = useState('')
  const [modifyingAddon, setModifyingAddon] = useState(false)

  function handleSubmitFeedback() {
    if (!feedbackText.trim() || !onSubmitFeedback) return
    onSubmitFeedback(plan.id, feedbackText.trim())
    setFeedbackText('')
    setModifyingAddon(false)
  }

  function handleChipClick(text: string) {
    setFeedbackText(text)
  }

  function handleCancelModify() {
    setFeedbackText('')
    setModifyingAddon(false)
    onCancelModify?.()
  }

  function handleModifyAddon() {
    setModifyingAddon(true)
    setFeedbackText('换一个加餐')
    onModify?.(plan.id)
  }

  const showFeedback = isModifying && !disabled && !revisionLoading
  const addonLocked = plan.lockedStages.includes('addon')

  return (
    <div className="plan-card">
      {/* Header */}
      <div className="plan-card-header">
        <span className="plan-card-title">{plan.title}</span>
        <div className="plan-card-badges">
          {plan.version > 1 && (
            <span className="plan-card-badge version-badge">v{plan.version}</span>
          )}
          <span className="plan-card-badge score-badge">{plan.score}分</span>
        </div>
      </div>

      {/* Detailed Timeline */}
      <div className="plan-timeline-detailed">
        {/* First transit: 出发 → play */}
        <TransitRow
          transit={{
            from: '出发',
            to: plan.play.name,
            startTime: '',
            endTime: plan.play.startTime,
            durationMin: 0,
            mode: '出发',
          }}
          isFirst
        />

        {/* Play stage */}
        <StageRow
          stage={plan.play}
          icon="🎯"
          label="活动"
          locked={plan.lockedStages.includes('play')}
        />

        {/* Transits between play → addon → eat */}
        {plan.transits.map((t, i) => (
          <TransitRow key={`t-${i}`} transit={t} />
        ))}

        {/* Addon card (highlighted, separate) */}
        {plan.addon && !plan.transits.some((t) => t.to === plan.addon!.name) && (
          <TransitRow
            transit={{
              from: plan.play.name,
              to: plan.addon.name,
              startTime: plan.play.endTime,
              endTime: plan.addon.startTime,
              durationMin: 0,
              mode: '步行',
            }}
          />
        )}

        {plan.addon && (
          <div className={`addon-card ${addonLocked ? 'stage-locked' : ''}`}>
            <div className="addon-card-header">
              <span className="addon-label">🧋 顺路加餐</span>
              {addonLocked && <span className="locked-badge" title="已锁定，不会修改">🔒</span>}
              {!addonLocked && !disabled && (
                <button
                  className="addon-modify-btn"
                  onClick={handleModifyAddon}
                  disabled={revisionLoading}
                  title="修改加餐"
                >
                  换
                </button>
              )}
            </div>
            <div className="addon-card-body">
              <div className="addon-name">{plan.addon.name}</div>
              <div className="addon-time">{plan.addon.time}</div>
              <div className="addon-desc">{plan.addon.desc}</div>
              {plan.addon.meta && (
                <div className="addon-meta">
                  {plan.addon.meta.avg_price != null && (
                    <span className="addon-meta-tag">¥{String(plan.addon.meta.avg_price)}</span>
                  )}
                  {plan.addon.meta.distance_km != null && (
                    <span className="addon-meta-tag">约{String(plan.addon.meta.distance_km)}km</span>
                  )}
                </div>
              )}
              <div className="timeline-tags">
                {plan.addon.tags.map((t, i) => (
                  <span key={i} className="tag">{t}</span>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Eat stage */}
        <StageRow
          stage={plan.eat}
          icon="🍽️"
          label="用餐"
          locked={plan.lockedStages.includes('food')}
        />
      </div>

      {/* Highlights */}
      <div className="plan-highlights">
        {plan.highlights.map((h, i) => (
          <span key={i} className="highlight-tag">{h}</span>
        ))}
      </div>

      {/* Feedback input (shown when modifying this plan) */}
      {showFeedback && (
        <div className="feedback-area">
          {modifyingAddon && (
            <div className="feedback-hint">想换什么加餐？也可以直接输入任意修改建议</div>
          )}
          <div className="feedback-chips">
            {QUICK_CHIPS.map((chip) => (
              <button
                key={chip.label}
                className="feedback-chip"
                onClick={() => handleChipClick(chip.text)}
              >
                {chip.label}
              </button>
            ))}
          </div>
          <div className="feedback-input-row">
            <input
              className="feedback-input"
              type="text"
              value={feedbackText}
              onChange={(e) => setFeedbackText(e.target.value)}
              placeholder="如：餐厅换个日料，公园别动..."
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleSubmitFeedback()
                if (e.key === 'Escape') handleCancelModify()
              }}
              autoFocus
            />
            <button
              className="feedback-submit-btn"
              onClick={handleSubmitFeedback}
              disabled={!feedbackText.trim()}
            >
              确定
            </button>
            <button
              className="feedback-cancel-btn"
              onClick={handleCancelModify}
            >
              取消
            </button>
          </div>
        </div>
      )}

      {/* Footer */}
      <div className="plan-card-footer">
        <span className="plan-price">{plan.totalPrice}</span>
        <div className="plan-card-actions">
          {!disabled && onModify && !showFeedback && (
            <button
              className="modify-btn"
              onClick={() => onModify(plan.id)}
              disabled={revisionLoading}
            >
              修改
            </button>
          )}
          <button
            className="confirm-btn"
            onClick={() => onConfirm(plan.id)}
            disabled={disabled || revisionLoading}
          >
            选这个
          </button>
        </div>
      </div>
    </div>
  )
}

function StageRow({
  stage,
  icon,
  label,
  locked,
}: {
  stage: DisplayStage
  icon: string
  label: string
  locked?: boolean
}) {
  return (
    <div className={`stage-row ${locked ? 'stage-locked' : ''}`}>
      <div className="stage-marker">
        <span className="stage-emoji">{icon}</span>
        <div className="stage-line" />
      </div>
      <div className="stage-content">
        <div className="stage-header">
          <span className="stage-label">{label}</span>
          <span className="stage-time">
            {stage.startTime}-{stage.endTime}
            {locked && <span className="locked-badge" title="已锁定">🔒</span>}
          </span>
        </div>
        <div className="stage-name">{stage.name}</div>
        <div className="stage-desc">{stage.desc}</div>
        <div className="timeline-tags">
          {stage.tags.map((t, i) => (
            <span key={i} className="tag">{t}</span>
          ))}
        </div>
      </div>
    </div>
  )
}

function TransitRow({
  transit,
  isFirst,
}: {
  transit: DisplayTransit
  isFirst?: boolean
}) {
  const distStr = transit.distanceKm != null
    ? `${transit.distanceKm < 1 ? `${Math.round(transit.distanceKm * 1000)}m` : `${transit.distanceKm}km`}`
    : ''
  const detail = [transit.mode, distStr, transit.durationMin > 0 ? `${transit.durationMin}分钟` : '']
    .filter(Boolean)
    .join(' · ')

  return (
    <div className={`transit-row ${isFirst ? 'transit-first' : ''}`}>
      <div className="transit-marker">
        <span className="transit-icon">{isFirst ? '📍' : '🚗'}</span>
        {!isFirst && <div className="transit-line-dashed" />}
      </div>
      <div className="transit-content">
        {isFirst ? (
          <div className="transit-text">
            出发前往 <strong>{transit.to}</strong>
            {transit.endTime && <span className="transit-time">预计 {transit.endTime} 到达</span>}
          </div>
        ) : (
          <div className="transit-text">
            <span className="transit-time-tag">{transit.startTime}-{transit.endTime}</span>
            {detail && <span className="transit-detail">{detail}</span>}
            {transit.note && <span className="transit-note">{transit.note}</span>}
          </div>
        )}
      </div>
    </div>
  )
}
