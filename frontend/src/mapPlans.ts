import type { BackendPlanPayload, DisplayPlan, PlanTimelineItem, PlanVenue } from './types'

const STAGE_LABELS: Record<string, string> = {
  play: '活动',
  eat: '餐厅',
  addon: '加餐',
}

function emptyVenue(): PlanVenue {
  return { name: '—', time: '—', desc: '', tags: [], priceLabel: '', distanceLabel: '' }
}

function venueExtras(v?: { priceLabel?: string; distanceLabel?: string }) {
  return {
    priceLabel: v?.priceLabel ?? '',
    distanceLabel: v?.distanceLabel ?? '',
  }
}

function parseStageOrder(orderLabel?: string): Array<'玩' | '吃' | '加餐'> {
  if (!orderLabel) return ['玩', '吃']
  return orderLabel
    .split(/\s*→\s*/)
    .map((s) => s.trim())
    .filter((s): s is '玩' | '吃' | '加餐' => s === '玩' || s === '吃' || s === '加餐')
}

function buildTimeline(
  p: BackendPlanPayload,
  order: Array<'玩' | '吃' | '加餐'>,
): PlanTimelineItem[] {
  const items: PlanTimelineItem[] = []

  for (const stage of order) {
    if (stage === '玩' && p.play) {
      items.push({
        kind: 'play',
        label: STAGE_LABELS.play,
        time: p.play.time,
        name: p.play.name,
        desc: p.play.desc,
        tags: p.play.tags,
        ...venueExtras(p.play),
      })
    } else if (stage === '吃' && p.eat) {
      items.push({
        kind: 'eat',
        label: STAGE_LABELS.eat,
        time: p.eat.time,
        name: p.eat.name,
        desc: p.eat.desc,
        tags: p.eat.tags,
        ...venueExtras(p.eat),
      })
    } else if (stage === '加餐' && p.addon) {
      items.push({
        kind: 'addon',
        label: STAGE_LABELS.addon,
        time: '顺路',
        name: p.addon.name,
        desc: p.addon.desc,
        tags: p.addon.tags,
        ...venueExtras(p.addon),
      })
    }
  }

  if (!items.length) {
    if (p.play) {
      items.push({
        kind: 'play',
        label: STAGE_LABELS.play,
        time: p.play.time,
        name: p.play.name,
        desc: p.play.desc,
        tags: p.play.tags,
        ...venueExtras(p.play),
      })
    }
    if (p.eat) {
      items.push({
        kind: 'eat',
        label: STAGE_LABELS.eat,
        time: p.eat.time,
        name: p.eat.name,
        desc: p.eat.desc,
        tags: p.eat.tags,
        ...venueExtras(p.eat),
      })
    }
  }

  return items
}

function venueChainFromTimeline(timeline: PlanTimelineItem[]): string {
  return timeline.map((t) => t.name).join(' → ')
}

const LIGHT_KEYS = ['轻食', '低卡', '沙拉', '健康']
const HEAVY_KEYS = ['烤肉', '火锅', '重口味', '烧烤', '川菜', '湘菜']

function includesAny(text: string, keys: string[]) {
  return keys.some((k) => text.includes(k))
}

function validateFrontendConstraints(
  p: BackendPlanPayload,
  matchReasons: string[],
): string[] {
  const issues = [...(p.constraintIssues ?? [])]
  const eatText = [
    p.eat?.name,
    p.eat?.desc,
    ...(p.eat?.tags ?? []),
  ].filter(Boolean).join(' ')
  const reasonText = matchReasons.join(' ')

  const claimsLight = includesAny(reasonText, ['轻食', '低卡'])
  if (claimsLight && includesAny(eatText, HEAVY_KEYS)) {
    issues.push('前端校验：轻食/低卡约束与当前餐厅类型冲突')
  }
  if (claimsLight && eatText && !includesAny(eatText, LIGHT_KEYS)) {
    issues.push('前端校验：餐厅缺少轻食/低卡标签')
  }

  return Array.from(new Set(issues))
}

export function mapPlansFromBackend(plans: BackendPlanPayload[]): DisplayPlan[] {
  if (!plans.length) return []

  return plans.map((p) => {
    const orderLabel = p.order_label ?? '玩 → 吃'
    const order = parseStageOrder(orderLabel)
    const timeline = buildTimeline(p, order)
    const venueChain = venueChainFromTimeline(timeline)

    const matchReasons = p.matchReasons?.length
      ? p.matchReasons
      : p.highlights?.length
        ? p.highlights
        : []
    const extraIssues = validateFrontendConstraints(p, matchReasons)
    const planIssues = p.planIssues?.length
      ? p.planIssues
      : extraIssues.map((detail) => ({
          code: 'constraint_mismatch',
          headline: '方案与偏好不完全匹配',
          detail,
          suggestions: ['修改偏好后重新规划'],
          allowAcceptAlternative: false,
        }))
    const issueKind = p.issueKind ?? (planIssues.length ? 'blocked' : 'ok')
    const constraintIssues = planIssues.map((i) => i.detail)

    return {
      id: p.id,
      title: p.title,
      orderLabel,
      venueChain,
      diffSummary: p.diffSummary ?? (p.id === 'primary' ? '综合评分最高' : '备选方案'),
      activeConstraints: p.activeConstraints ?? [],
      play: p.play ?? emptyVenue(),
      eat: p.eat ?? emptyVenue(),
      addon: p.addon,
      addons: p.addons,
      timeline,
      totalPrice: p.totalPrice ?? '—',
      score: p.score ?? 0,
      highlights: matchReasons.length ? matchReasons : [orderLabel],
      matchReasons,
      planIssues,
      issueKind,
      allowAcceptAlternative: p.allowAcceptAlternative ?? false,
      constraintIssues,
      isValid: (p.isValid ?? true) && extraIssues.length === 0,
      isCompromised: p.isCompromised ?? false,
      compromiseMessage: p.compromiseMessage ?? '',
      compromiseSource: p.compromiseSource ?? '',
    }
  })
}
