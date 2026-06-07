import type { ScenarioId } from '../scenarioPresets'

interface Props {
  greeting: string
  onScenarioSelect: (id: ScenarioId) => void
  disabled: boolean
}

export function WelcomeScreen({ greeting, onScenarioSelect, disabled }: Props) {
  return (
    <div className="ai-bubble welcome-bubble">
      <div className="bubble-text welcome-text">{greeting}</div>
      <div className="welcome-hint">
        推荐先选「朋友」：只说重口味，档案会 Mock 唤醒禁辣——点右下角 Trace 可看。
      </div>
      <div className="scenario-cards">
        <button
          type="button"
          className="scenario-card scenario-card-family"
          onClick={() => onScenarioSelect('family')}
          disabled={disabled}
        >
          <div className="scenario-card-title">家庭场景</div>
          <div className="scenario-card-desc">3 人 · 5 岁娃 · 亲子活动</div>
          <div className="scenario-card-tip">可再加：火锅 / 轻食 / 日料</div>
        </button>
        <button
          type="button"
          className="scenario-card scenario-card-friends"
          onClick={() => onScenarioSelect('friends')}
          disabled={disabled}
        >
          <div className="scenario-card-title">朋友场景</div>
          <div className="scenario-card-desc">4 人 · 重口味 · 社交聚餐</div>
          <div className="scenario-card-tip">痔疮档案 Mock → 禁辣冲突 → 满座 Recovery</div>
        </button>
      </div>
    </div>
  )
}
