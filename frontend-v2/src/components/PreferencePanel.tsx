import type { PreferenceState } from '../types'

interface Props {
  preferences: PreferenceState
  onChange: (prefs: PreferenceState) => void
  onConfirm: () => void
}

export function PreferencePanel({ preferences, onChange, onConfirm }: Props) {
  function toggleFoodTag(id: string) {
    onChange({
      ...preferences,
      foodTags: preferences.foodTags.map((t) =>
        t.id === id ? { ...t, selected: !t.selected } : t,
      ),
    })
  }

  function toggleActivityTag(id: string) {
    onChange({
      ...preferences,
      activityTags: preferences.activityTags.map((t) =>
        t.id === id ? { ...t, selected: !t.selected } : t,
      ),
    })
  }

  function movePriority(id: string, direction: -1 | 1) {
    const idx = preferences.priorities.findIndex((p) => p.id === id)
    if (idx === -1) return
    const newIdx = idx + direction
    if (newIdx < 0 || newIdx >= preferences.priorities.length) return
    const next = [...preferences.priorities]
    ;[next[idx], next[newIdx]] = [next[newIdx], next[idx]]
    onChange({
      ...preferences,
      priorities: next.map((p, i) => ({ ...p, order: i })),
    })
  }

  const hasSelection =
    preferences.foodTags.some((t) => t.selected) ||
    preferences.activityTags.some((t) => t.selected)

  return (
    <div className="preference-panel">
      {/* Section 1: Food taste */}
      <div className="pref-section">
        <div className="pref-label">今天的胃口适合遇见谁？</div>
        <div className="tag-grid">
          {preferences.foodTags.map((tag) => (
            <button
              key={tag.id}
              className={`pref-tag food-tag ${tag.selected ? 'selected' : ''} ${tag.recommended ? 'recommended' : ''}`}
              onClick={() => toggleFoodTag(tag.id)}
            >
              <span className="tag-emoji">{tag.emoji}</span>
              <span>{tag.label}</span>
              {tag.recommended && <span className="rec-badge">推荐</span>}
            </button>
          ))}
        </div>
      </div>

      {/* Section 2: Activity preferences */}
      <div className="pref-section">
        <div className="pref-label">据说这里非常适合拍照打卡！</div>
        <div className="tag-grid">
          {preferences.activityTags.map((tag) => (
            <button
              key={tag.id}
              className={`pref-tag activity-tag ${tag.selected ? 'selected' : ''} ${tag.recommended ? 'recommended' : ''}`}
              onClick={() => toggleActivityTag(tag.id)}
            >
              <span className="tag-emoji">{tag.emoji}</span>
              <span>{tag.label}</span>
              {tag.recommended && <span className="rec-badge">推荐</span>}
            </button>
          ))}
        </div>
      </div>

      {/* Section 3: Priority sorting */}
      <div className="pref-section">
        <div className="pref-label">让我来规划，你来保持放松好心情！请选择你的偏好排序：</div>
        <div className="priority-list">
          {preferences.priorities
            .sort((a, b) => a.order - b.order)
            .map((p, i) => (
              <div key={p.id} className="priority-item">
                <span className="priority-rank">{i + 1}</span>
                <span className="priority-emoji">{p.emoji}</span>
                <span className="priority-label">{p.label}</span>
                <div className="priority-arrows">
                  <button
                    className="arrow-btn"
                    disabled={i === 0}
                    onClick={() => movePriority(p.id, -1)}
                  >
                    ▲
                  </button>
                  <button
                    className="arrow-btn"
                    disabled={i === preferences.priorities.length - 1}
                    onClick={() => movePriority(p.id, 1)}
                  >
                    ▼
                  </button>
                </div>
              </div>
            ))}
        </div>
      </div>

      <button
        className="pref-confirm-btn"
        onClick={onConfirm}
        disabled={!hasSelection}
      >
        {hasSelection ? '按此偏好开始规划' : '请至少选择一个偏好'}
      </button>
    </div>
  )
}
