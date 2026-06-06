import { useEffect, useRef } from 'react'
import { ProgressIndicator } from './ProgressIndicator'

interface Props {
  currentNode: string
  agentLogs: string[]
  isProcessing: boolean
}

export function AgentDashboard({ currentNode, agentLogs, isProcessing }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [agentLogs.length])

  return (
    <div className="agent-dashboard">
      <div className="agent-dashboard-header">
        <h3 className="agent-dashboard-title">
          <span>⚙️ LangGraph Core Agentic Engine Dashboard</span>
          {isProcessing && <span className="agent-dashboard-pulse" />}
        </h3>
        <ProgressIndicator currentNode={currentNode} live={isProcessing} />
      </div>

      <div className="agent-log-panel">
        <div className="agent-log-kicker">// 实时思维轨迹链路跟踪 (LLM Trace Panel)</div>
        {agentLogs.length === 0 ? (
          <div className="agent-log-empty">
            左侧选择场景或开始规划后，这里会按 LangGraph 节点追加 Trace。
          </div>
        ) : (
          agentLogs.map((log, i) => (
            <div key={`${i}-${log.slice(0, 24)}`} className="agent-log-line">
              <span className="agent-log-arrow">➜</span> {log}
            </div>
          ))
        )}
        {isProcessing && <div className="agent-log-cursor">█ 思考规划中...</div>}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
