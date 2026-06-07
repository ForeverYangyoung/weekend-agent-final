import type { ScenarioId } from '../scenarioPresets'

interface Props {
  onScenarioSelect: (id: ScenarioId) => void
  disabled: boolean
}

export function WelcomeScreen({ onScenarioSelect, disabled }: Props) {
  return (
    <div className="ai-bubble welcome-bubble">
      <div className="welcome-title">周末出游，交给我来安排</div>
      <p className="welcome-lead">
        告诉我你想带家人还是朋友出去——我帮你排好 <strong>玩 → 吃 → 附加</strong>，
        查好空位，确认后一键代订。
      </p>
      <ol className="welcome-steps">
        <li>选一个场景（或底部自己输入）</li>
        <li>看两张方案卡，不满意可微调</li>
        <li>想看 Agent 怎么打分、怎么自愈？点右下角 <strong>Trace</strong></li>
      </ol>
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
          <div className="scenario-card-tip">推荐首试：档案 Mock · 满座自愈</div>
        </button>
      </div>
    </div>
  )
}
