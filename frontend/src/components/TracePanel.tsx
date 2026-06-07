import { useEffect, useRef } from 'react'
import { humanizeTraceLine, isCompareTraceLine, isUiTraceLine } from '../traceHumanize'
import {
  isBackoffTraceLine,
  isCompromiseTraceLine,
  isScoreFormulaLine,
  isScoreLegendStreamLine,
  SCORE_LEGEND_LINES,
} from '../traceScoreLegend'
import { stepLabel } from '../traceUi'

interface Props {
  lines: string[]
  live?: boolean
  currentStep?: string | null
}

function traceLineClass(human: string, raw: string): string {
  const text = `${human} ${raw}`
  if (isUiTraceLine(raw)) {
    return 'trace-line trace-line-ui'
  }
  if (isScoreLegendStreamLine(raw)) {
    return 'trace-line trace-line-legend-stream'
  }
  if (isBackoffTraceLine(raw)) {
    return 'trace-line trace-line-backoff trace-line-strong'
  }
  if (isCompromiseTraceLine(raw)) {
    return 'trace-line trace-line-compromise trace-line-strong'
  }
  if (isScoreFormulaLine(raw)) {
    return raw.includes('算式·方案')
      ? 'trace-line trace-line-score trace-line-score-plan'
      : 'trace-line trace-line-score trace-line-score-poi'
  }
  if (/历史档案唤醒|History Archive/i.test(raw)) {
    return 'trace-line trace-line-recovery trace-line-strong'
  }
  if (isCompareTraceLine(raw)) {
    return 'trace-line trace-line-compare'
  }
  if (/order_addon|deliver_to_poi_id|addon delivery anchored|并入加餐|SummaryCard|规则校验通过|预检通过/i.test(text)) {
    return 'trace-line trace-line-ok trace-line-strong'
  }
  if (/FAIL 店=|DryRun \| 订座|不可用|满座|409|Recovery启动|mock_trap/i.test(text)) {
    return 'trace-line trace-line-danger trace-line-strong'
  }
  if (/Recovery Replan|重规划|blocked POI|Recovery 启动|recovery\//i.test(text)) {
    return 'trace-line trace-line-recovery trace-line-strong'
  }
  if (/✗|失败|回滚|有问题/i.test(text)) {
    return 'trace-line trace-line-warn'
  }
  if (/重搜|换方案|重排/i.test(text)) {
    return 'trace-line trace-line-accent'
  }
  if (/✓|通过|都能订|正式下单|行程卡|提交成功/i.test(text)) {
    return 'trace-line trace-line-ok'
  }
  return 'trace-line'
}

function ScoreLegendBox({ show }: { show: boolean }) {
  if (!show) return null
  return (
    <div className="trace-score-legend">
      <div className="trace-score-legend-title">打分算式图例（各项含义）</div>
      {SCORE_LEGEND_LINES.map((line) => (
        <div
          key={line}
          className={
            line.startsWith('【')
              ? 'trace-score-legend-section'
              : 'trace-score-legend-item'
          }
        >
          {line}
        </div>
      ))}
    </div>
  )
}

export function TracePanel({ lines, live, currentStep }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)
  const hasScoreContent = lines.some(isScoreFormulaLine)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [lines.length])

  const displayLines = lines.filter((line) => !isScoreLegendStreamLine(line))

  return (
    <div className="trace-panel">
      <div className="trace-panel-header">
        <div>
          <div className="trace-panel-title">Agent 执行 Trace</div>
          <div className="trace-panel-subtitle">
            {currentStep
              ? `当前步骤：${stepLabel(currentStep)}`
              : 'Profiler → Researcher → Planner → DryRun → 确认'}
          </div>
        </div>
        {live && <span className="trace-live-badge">进行中</span>}
      </div>
      <div className="trace-panel-body">
        <ScoreLegendBox show={hasScoreContent} />
        {displayLines.length === 0 ? (
          <div className="trace-empty">
            左侧选择场景或开始规划后，这里会按步骤追加 Trace；出现算式行后，顶部图例会说明每项含义。
          </div>
        ) : (
          displayLines.map((line, i) => {
            const human = humanizeTraceLine(line)
            return (
              <div key={`${i}-${line.slice(0, 32)}`} className={traceLineClass(human, line)}>
                <div className="trace-human">{human}</div>
              </div>
            )
          })
        )}
        {live && <div className="agent-log-cursor">█ 思考规划中...</div>}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
