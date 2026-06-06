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

const TITLES: Record<NonNullable<HilInterruptCtx['kind']>, string> = {
  recovery: '这家餐厅暂时订不到了',
  conflict: '偏好需要您拍板一下',
  error: '规划时出了点小状况',
}

export function HilInterruptModal({ interrupt, onResume, onDismiss, loading }: Props) {
  const kind = interrupt.kind ?? 'error'
  const title = TITLES[kind]

  return (
    <div className="hil-interrupt-overlay">
      <div className="hil-interrupt-modal">
        <h4 className="hil-interrupt-title">{title}</h4>
        <p className="hil-interrupt-reason">{interrupt.reason}</p>
        <div className="hil-interrupt-actions">
          {kind === 'error' && (
            <button
              type="button"
              onClick={onResume}
              disabled={loading}
              className="hil-interrupt-btn hil-interrupt-btn-primary"
            >
              {loading ? '正在重新规划…' : '帮我重新规划'}
            </button>
          )}
          <button
            type="button"
            onClick={onDismiss}
            disabled={loading}
            className={`hil-interrupt-btn ${
              kind === 'error' ? 'hil-interrupt-btn-secondary' : 'hil-interrupt-btn-primary'
            }`}
          >
            {kind === 'conflict' ? '我知道了' : kind === 'recovery' ? '好的，看新方案' : '先不用了'}
          </button>
        </div>
      </div>
    </div>
  )
}
