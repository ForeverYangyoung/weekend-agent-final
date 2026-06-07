/** 与 backend/trace_score.py SCORE_LEGEND_LINES 保持一致 */
export const SCORE_LEGEND_LINES: readonly string[] = [
  '【POI 五维分】Researcher 对每家候选店打分，加权求和 = 单店总分',
  '  偏好 35% — 标签/菜系/场景是否匹配用户画像（0~1，越高越贴偏好）',
  '  历史 20% — 用户历史偏好权重命中（0~1，无历史时默认 0.5）',
  '  评分 20% — Mock 平台 POI 评分（0~1）',
  '  距离 15% — Sigmoid 平滑：1/(1+e^(2×(实际km-上限km)))，越近越高，超距不砍店只降分',
  '  预算 10% — 仅「吃」阶段：人均≤预算→1；超出→e^(-5×超出比例)，轻微超支可容忍',
  '【方案全局分】Planner 对「玩+吃」组合打分',
  '  基础均分 = (玩 POI 总分 + 吃 POI 总分) ÷ 2',
  '  顺路惩罚 = 1 - e^(-0.5×max(0, |d玩-d吃|-3km))；差≤3km 时惩罚=0',
  '  方案分 = 基础均分 × (1 - 0.4 × 顺路惩罚)',
  '【内存退避】一次拉池20家，严苛不足时在内存放宽距离+3km、预算+30% 重排',
  '【妥协保底】硬过滤无匹配时取综合分最高，Plan.is_compromised 触发前端黄条',
]

export function isScoreFormulaLine(raw: string): boolean {
  return /算式·(POI|方案|图例)/.test(raw)
}

export function isBackoffTraceLine(raw: string): boolean {
  return /严苛·|退避·/.test(raw)
}

export function isCompromiseTraceLine(raw: string): boolean {
  return /妥协·/.test(raw)
}

export function isScoreLegendStreamLine(raw: string): boolean {
  return /算式·图例/.test(raw)
}
