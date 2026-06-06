import type { ProfileChip, ProfileOverride } from '../types'
import type { ScenarioPreset } from '../scenarioPresets'
import { ProfileChips } from './ProfileChips'

interface Props {
  preset: ScenarioPreset
  chips: ProfileChip[]
  onRemove: (override: ProfileOverride) => void
  onAdd: (override: ProfileOverride) => void
  onStart: () => void
  onCancel: () => void
  disabled?: boolean
}

export function ScenarioSetup({
  preset,
  chips,
  onRemove,
  onAdd,
  onStart,
  onCancel,
  disabled,
}: Props) {
  return (
    <div className="scenario-setup">
      <div className="scenario-setup-head">
        <div className="scenario-setup-title">已选：{preset.title}</div>
        <div className="scenario-setup-desc">
          先确认/补充偏好再规划。例如家庭场景可再加「火锅」，不会锁死轻食。
        </div>
      </div>
      <ProfileChips
        chips={chips}
        editing
        onRemove={onRemove}
        onAdd={onAdd}
        onReplan={onStart}
        replanning={disabled}
        replanLabel="按此偏好开始规划"
      />
      <button type="button" className="scenario-cancel-btn" onClick={onCancel} disabled={disabled}>
        换场景
      </button>
    </div>
  )
}
