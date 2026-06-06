interface Props {
  greeting: string
  prompts: string[]
  onPromptClick: (text: string) => void
  disabled: boolean
}

export function WelcomeScreen({ greeting, prompts, onPromptClick, disabled }: Props) {
  return (
    <div className="ai-bubble welcome-bubble">
      <div className="bubble-text welcome-text">{greeting}</div>
      <div className="welcome-hint">可以像这样说"我下午想和老婆孩子一起出去玩……"</div>
      <div className="welcome-hint">也可以输入"选择"，直接在我提供的选项中选择游玩和饮食偏好</div>
      <div className="welcome-prompts">
        {prompts.map((p, i) => (
          <button
            key={i}
            className="prompt-chip"
            onClick={() => onPromptClick(p)}
            disabled={disabled}
          >
            {p}
          </button>
        ))}
      </div>
    </div>
  )
}
