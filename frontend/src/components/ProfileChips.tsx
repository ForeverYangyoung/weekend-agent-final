import type { FormEvent } from 'react'
import type { ProfileChip, ProfileOverride } from '../types'

interface Props {
  chips: ProfileChip[]
  editing: boolean
  onRemove: (override: ProfileOverride) => void
  onAdd: (override: ProfileOverride) => void
  onReplan: () => void
  replanning?: boolean
  replanLabel?: string
}

const CUISINE_HINTS = ['重口味', '川菜', '火锅', '粤菜', '日料', '轻食', '烤肉']

function parsePreferenceInput(text: string): ProfileOverride | null {
  const trimmed = text.trim()
  if (!trimmed) return null

  if (/区/.test(trimmed) || /海淀|朝阳|西城|东城|丰台/.test(trimmed)) {
    const district = trimmed.includes('区') ? trimmed : `${trimmed}区`
    return { key: 'district', value: district, action: 'set' }
  }

  const peopleMatch = trimmed.match(/(\d+)\s*人/)
  if (peopleMatch) {
    return { key: 'people_count', value: peopleMatch[1], action: 'set' }
  }

  if (/重口味|重口|口味重/.test(trimmed)) {
    return { key: 'dietary', value: '重口味', action: 'add' }
  }
  if (/低卡|减肥|轻食/.test(trimmed)) {
    return { key: 'dietary', value: '低卡', action: 'add' }
  }

  const cuisine = CUISINE_HINTS.find((c) => trimmed.includes(c))
  if (cuisine) {
    return { key: 'dietary', value: cuisine, action: 'add' }
  }

  const budgetMatch = trimmed.match(/(\d+)/)
  if (/预算|以内|不超过|元/.test(trimmed) && budgetMatch) {
    return { key: 'budget_per_person', value: budgetMatch[1], action: 'set' }
  }

  return { key: 'interests', value: trimmed, action: 'add' }
}

export function ProfileChips({
  chips,
  editing,
  onRemove,
  onAdd,
  onReplan,
  replanning,
  replanLabel = '按新偏好重新规划',
}: Props) {
  function handleAddInput(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const fd = new FormData(e.currentTarget)
    const text = String(fd.get('pref') ?? '')
    const override = parsePreferenceInput(text)
    if (override) {
      onAdd(override)
      e.currentTarget.reset()
    }
  }

  return (
    <div className="profile-chips-panel">
      <div className="profile-chips-title">
        {editing
          ? 'Profiler 提取的约束（点 × 删除 / 下方添加后重规划）'
          : 'Profiler 已提取约束'}
      </div>
      <div className="profile-chips">
        {chips.map((chip) => (
          <span
            key={`${chip.key}-${chip.value}-${chip.label}`}
            className={`profile-chip${chip.source === 'history' ? ' profile-chip-history' : ''}`}
            title={
              chip.source === 'history'
                ? 'Zero-Skill Mock · 跨端健康档案自动注入（如痔疮恢复期禁辣）'
                : undefined
            }
          >
            <span>{chip.label}</span>
            {chip.source === 'history' && <span className="profile-chip-source">档案</span>}
            {editing && (
              <button
                type="button"
                className="profile-chip-remove"
                aria-label={`移除 ${chip.label}`}
                onClick={() =>
                  onRemove({
                    key: chip.key,
                    value: chip.value,
                    action: 'remove',
                  })
                }
              >
                ×
              </button>
            )}
          </span>
        ))}
        {!chips.length && <span className="profile-chips-empty">暂无标签，可在下方补充</span>}
      </div>

      {editing && (
        <>
          <form className="profile-chip-add" onSubmit={handleAddInput}>
            <input
              name="pref"
              type="text"
              placeholder="添加偏好，如：火锅、海淀区、预算80"
              disabled={replanning}
            />
            <button type="submit" disabled={replanning}>
              添加
            </button>
          </form>
          <div className="profile-chip-quick">
            {CUISINE_HINTS.map((c) => (
              <button
                key={c}
                type="button"
                className="profile-chip-quick-btn"
                disabled={replanning}
                onClick={() => onAdd({ key: 'dietary', value: c, action: 'add' })}
              >
                +{c}
              </button>
            ))}
          </div>
          <button
            type="button"
            className="replan-btn"
            onClick={onReplan}
            disabled={replanning}
          >
            {replanning ? '规划中…' : replanLabel}
          </button>
        </>
      )}
    </div>
  )
}
