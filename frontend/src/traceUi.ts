/** 左侧用户操作 → 右侧 Trace 同步（与后端 Agent trace 区分） */

export function uiTraceLine(phase: string, message: string): string {
  return `[UI·${phase}] ${message}`
}

export const STEP_LABELS: Record<string, string> = {
  profiler: 'Profiler · 画像抽取',
  hil_apply: 'HIL · 偏好覆盖',
  researcher: 'Researcher · 候选召回',
  planner: 'Planner · 方案组合',
  targeted_researcher: 'TargetedResearcher · 精准补搜',
  critic: 'Critic · 规则校验',
  dry_run: 'DryRun · 读类预检',
  'recovery/planner': 'Recovery · 换店重排',
  'recovery/targeted_researcher': 'Recovery · 补搜',
  'recovery/critic': 'Recovery · 再校验',
  'recovery/dry_run': 'Recovery · 再预检',
}

export function stepLabel(step: string): string {
  return STEP_LABELS[step] ?? step
}
