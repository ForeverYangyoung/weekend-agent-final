import type { ProgressStep } from '../types'
import { stepLabel } from '../traceUi'

/** LangGraph 主链路节点（Final 版状态机） */
export const LANGGRAPH_NODES = [
  { id: 'START', label: 'START' },
  { id: 'profiler', label: 'Profiler' },
  { id: 'researcher', label: 'Researcher' },
  { id: 'planner', label: 'Planner' },
  { id: 'targeted_researcher', label: 'TargetedResearcher' },
  { id: 'critic', label: 'Critic' },
  { id: 'dry_run', label: 'DryRun' },
  { id: 'awaiting_confirm', label: 'HIL' },
  { id: 'executor', label: 'Executor' },
  { id: 'END', label: 'END' },
] as const

export function normalizeGraphNode(node: string): string {
  if (!node || node === 'START') return 'START'
  if (node === 'END' || node === 'done') return 'END'
  if (node.startsWith('recovery/')) return 'dry_run'
  if (node === 'hil_apply') return 'profiler'
  if (node === 'awaiting_confirm') return 'awaiting_confirm'
  return node
}

interface NodeProps {
  currentNode: string
  live?: boolean
}

interface StepsProps {
  steps: ProgressStep[]
  live?: boolean
}

type Props = NodeProps | StepsProps

function isNodeMode(props: Props): props is NodeProps {
  return 'currentNode' in props
}

export function ProgressIndicator(props: Props) {
  if (isNodeMode(props)) {
    return <NodeProgressIndicator currentNode={props.currentNode} live={props.live} />
  }
  return <StepsProgressIndicator steps={props.steps} live={props.live} />
}

function NodeProgressIndicator({ currentNode, live }: NodeProps) {
  const active = normalizeGraphNode(currentNode)
  const activeIdx = LANGGRAPH_NODES.findIndex((n) => n.id === active)

  return (
    <div className={`graph-progress ${live ? 'graph-progress-live' : ''}`}>
      <div className="graph-progress-track">
        {LANGGRAPH_NODES.map((node, i) => {
          const done = activeIdx >= 0 && i < activeIdx
          const current = node.id === active
          const recovery = currentNode.startsWith('recovery/') && node.id === 'dry_run'
          return (
            <div
              key={node.id}
              className={`graph-progress-node ${done ? 'done' : ''} ${current ? 'active' : ''} ${recovery ? 'recovery' : ''}`}
            >
              <span className="graph-progress-dot">{done ? '✓' : current ? '●' : '○'}</span>
              <span className="graph-progress-label">{node.label}</span>
            </div>
          )
        })}
      </div>
      <div className="graph-progress-status">
        {live ? (
          <>
            <span className="graph-progress-spinner" />
            <span>
              当前节点：<strong>{stepLabel(currentNode)}</strong>
            </span>
          </>
        ) : (
          <span>状态机就绪 · 等待触发</span>
        )}
      </div>
    </div>
  )
}

function StepsProgressIndicator({ steps, live }: StepsProps) {
  return (
    <div className={`ai-bubble progress-bubble ${live ? 'progress-live' : ''}`}>
      <div className="progress-header">
        <span className="progress-spinner" />
        <span>正在为您规划中...</span>
      </div>
      <div className="progress-steps">
        {steps.map((step, i) => (
          <div key={i} className={`progress-step ${step.done ? 'done' : ''}`}>
            <span className="step-icon">{step.done ? <CheckIcon /> : <DotSpinner index={i} />}</span>
            <span className="step-label">{step.label}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function CheckIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
      <circle cx="8" cy="8" r="7" fill="var(--success)" />
      <path d="M5 8.5l2 2 4-4" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function DotSpinner({ index }: { index: number }) {
  return (
    <span className="dot-spinner" style={{ animationDelay: `${index * 0.2}s` }} />
  )
}
