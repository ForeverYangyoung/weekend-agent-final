import type { PanelPreferences } from '../types'

interface Props {
  open: boolean
  preferences: PanelPreferences
  onChange: (prefs: PanelPreferences) => void
  onClose: () => void
  onSubmit: (prefs: PanelPreferences) => void
}

const DISTANCE_OPTIONS = ['3公里内', '5公里内', '10公里内']
const DIET_OPTIONS = ['重口味', '轻食低卡', '火锅', '烤肉', '日料', '川菜']
const VIBE_OPTIONS = ['轻松社交', '亲子友好', '网红打卡', '安静约会']

export function PreferencePanel({ open, preferences, onChange, onClose, onSubmit }: Props) {
  if (!open) return null

  function update<K extends keyof PanelPreferences>(key: K, value: PanelPreferences[K]) {
    onChange({ ...preferences, [key]: value })
  }

  return (
    <div className="pref-overlay" onClick={onClose}>
      <div className="pref-sheet" onClick={(e) => e.stopPropagation()}>
        <div className="pref-sheet-header">
          <span className="pref-sheet-title">调整偏好并重提方案</span>
          <button type="button" className="pref-close-btn" onClick={onClose}>关闭</button>
        </div>

        <div className="pref-field">
          <label className="pref-field-label">距离范围</label>
          <select
            className="pref-select"
            value={preferences.distance}
            onChange={(e) => update('distance', e.target.value)}
          >
            {DISTANCE_OPTIONS.map((opt) => (
              <option key={opt} value={opt}>{opt}</option>
            ))}
          </select>
        </div>

        <div className="pref-field">
          <label className="pref-field-label">餐饮偏好</label>
          <select
            className="pref-select"
            value={preferences.diet}
            onChange={(e) => update('diet', e.target.value)}
          >
            {DIET_OPTIONS.map((opt) => (
              <option key={opt} value={opt}>{opt}</option>
            ))}
          </select>
        </div>

        <div className="pref-field">
          <label className="pref-field-label">氛围环境</label>
          <select
            className="pref-select"
            value={preferences.vibe}
            onChange={(e) => update('vibe', e.target.value)}
          >
            {VIBE_OPTIONS.map((opt) => (
              <option key={opt} value={opt}>{opt}</option>
            ))}
          </select>
        </div>

        <button
          type="button"
          className="btn-primary pref-submit-btn"
          onClick={() => onSubmit(preferences)}
        >
          按新偏好重新规划
        </button>
      </div>
    </div>
  )
}
