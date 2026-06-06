import type { ProgressStep } from '../types'

interface Props {
  steps: ProgressStep[]
  live?: boolean
}

export function ProgressIndicator({ steps, live }: Props) {
  return (
    <div className={`ai-bubble progress-bubble ${live ? 'progress-live' : ''}`}>
      <div className="progress-header">
        <span className="progress-spinner" />
        <span>正在为您规划中...</span>
      </div>
      <div className="progress-steps">
        {steps.map((step, i) => (
          <div key={i} className={`progress-step ${step.done ? 'done' : ''}`}>
            <span className="step-icon">{step.done ? <CheckIcon /> : <DotSpinner index={i} />}</span>
            <span className="step-label">{step.label}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function CheckIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
      <circle cx="8" cy="8" r="7" fill="var(--success)" />
      <path d="M5 8.5l2 2 4-4" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function DotSpinner({ index }: { index: number }) {
  return (
    <span className="dot-spinner" style={{ animationDelay: `${index * 0.2}s` }} />
  )
}
