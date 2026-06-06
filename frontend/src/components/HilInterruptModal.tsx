interface HilInterruptCtx {
  reason: string
  kind?: 'conflict' | 'recovery' | 'error'
}

interface Props {
  interrupt: HilInterruptCtx
  onResume: () => void
  onDismiss: () => void
  loading?: boolean
}

export function HilInterruptModal({ interrupt, onResume, onDismiss, loading }: Props) {
  return (
    <div className="hil-interrupt-overlay">
      <div className="hil-interrupt-modal">
        <h4 className="hil-interrupt-title">⚠️ 物理世界异常/群体冲突拦截</h4>
        <p className="hil-interrupt-reason">{interrupt.reason}</p>
        <div className="hil-interrupt-actions">
          {interrupt.kind !== 'conflict' && (
            <button
              type="button"
              onClick={onResume}
              disabled={loading}
              className="hil-interrupt-btn hil-interrupt-btn-primary"
            >
              {loading ? '容灾重规划中…' : '授权系统自动容灾'}
            </button>
          )}
          <button
            type="button"
            onClick={onDismiss}
            disabled={loading}
            className="hil-interrupt-btn hil-interrupt-btn-secondary"
          >
            {interrupt.kind === 'conflict' ? '我知道了' : '稍后处理'}
          </button>
        </div>
      </div>
    </div>
  )
}
