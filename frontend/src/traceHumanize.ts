/** 把后端 trace 行整理成答辩侧可讲解的专业链路口径 */

const SCENE_LABEL: Record<string, string> = {
  family: '家庭出游',
  friends: '朋友聚会',
  couple: '情侣约会',
  solo: '独自出行',
}

function pullBracketTag(line: string): string {
  const m = line.match(/^\[([^\]]+)\]\s*(.*)$/)
  if (!m) return line
  return m[2]
}

function parseListField(text: string, key: string): string[] {
  const m = text.match(new RegExp(`${key}=\\[([^\\]]*)\\]`))
  if (!m) return []
  const inner = m[1].trim()
  if (!inner) return []
  return inner
    .split(',')
    .map((s) => s.trim().replace(/^['"]|['"]$/g, ''))
    .filter(Boolean)
}

export function isCompareTraceLine(raw: string): boolean {
  return /对比·/.test(raw)
}

export function isUiTraceLine(raw: string): boolean {
  return raw.startsWith('[UI·')
}

export function humanizeTraceLine(raw: string): string {
  const body = pullBracketTag(raw)

  if (raw.startsWith('[UI·')) {
    return `UI Sync | ${body}`
  }

  if (body.includes('对比·')) {
    return body.replace(/对比·/g, 'COMPARE | ')
  }

  if (raw.includes('[Profiler]') && body.includes('[历史档案唤醒]')) {
    const detail = body.replace(/\[历史档案唤醒\]\s*/g, '').trim()
    return `Profiler | Zero-Skill·隐式画像(Mock) | ${detail}`
  }

  if (raw.includes('[Profiler]')) {
    const scene = body.match(/scene=(\w+)/)?.[1] ?? ''
    const people = body.match(/people=(\d+)/)?.[1]
    const start = body.match(/start=([^ ]+)/)?.[1]
    const dietary = parseListField(body, 'dietary')
    const interests = parseListField(body, 'interests')
    const parts = ['Profiler | 画像抽取完成']
    if (scene) parts.push(`scene=${SCENE_LABEL[scene] ?? scene}`)
    if (people) parts.push(`people=${people}`)
    if (start && start !== '—') parts.push(`start=${start}`)
    parts.push(`dietary=${dietary.length ? dietary.join('/') : 'none'}`)
    if (interests.length) parts.push(`interests=${interests.join('/')}`)
    return parts.join(' | ')
  }

  if (raw.includes('[HIL')) {
    if (body.includes('已应用')) {
      return `HIL | 用户偏好覆盖已写入 state | ${body.replace('已应用 ', '')}`
    }
    return `HIL | 触发画像覆盖与重规划 | ${body}`
  }

  if (raw.includes('[Researcher·候选]') || (raw.includes('[Researcher]') && body.includes('对比·'))) {
    return `Researcher | POI 候选榜 | ${body}`
  }

  if (raw.includes('[Researcher]')) {
    if (body.includes('初搜')) {
      const selected = body.split('｜')[1]
      return selected
        ? `Researcher | Mock POI 初搜完成 | top: ${selected}`
        : `Researcher | Mock POI 初搜完成 | ${body}`
    }
    return `Researcher | 候选集召回与打分 | ${body}`
  }

  if (raw.includes('[TargetedResearcher·候选]') || (raw.includes('[TargetedResearcher]') && body.includes('对比·'))) {
    return `TargetedResearcher | 精准候选榜 | ${body}`
  }

  if (raw.includes('[TargetedResearcher]')) {
    if (body.includes('跳过')) return 'TargetedResearcher | 无顺路加餐需求，跳过精准补搜'
    return `TargetedResearcher | 顺路加餐精准补搜 | ${body}`
  }

  if (raw.includes('[Planner·候选]') || raw.includes('[Planner·重规划]') || (raw.includes('[Planner]') && body.includes('对比·'))) {
    return `Planner | 方案对比榜 | ${body}`
  }

  if (raw.includes('[Planner]')) {
    if (body.includes('重规划')) {
      return `规划 | 满座后换店重排 | ${body}`
    }
    return `Planner | 首轮排程与 Top-K 方案生成 | ${body.replace('首次规划：', '')}`
  }

  if (raw.includes('[Critic')) {
    if (body.includes('并入加餐')) {
      return `Critic | 加餐并入方案 | ${body}`
    }
    if (body.includes('approved=False') || body.includes('✗')) {
      const n = body.match(/issues=(\d+)/)?.[1] ?? '若干'
      return `Critic | 规则校验未通过 | issues=${n} | 进入 Planner 修正`
    }
    return 'Critic | 规则校验通过 | constraints approved | 进入 DryRun'
  }

  if (raw.includes('[Executor·恢复]') || raw.includes('[DryRun·恢复]')) {
    return `预检 | 自动换店 | ${body}`
  }

  if (raw.includes('[DryRun·预检]') || raw.includes('[Executor·预检]')) {
    if (body.includes('FAIL 店=')) {
      return `DryRun | 订座/库存预检失败 | ${body}`
    }
    if (body.includes('OK  店=')) {
      return `DryRun | 单项预检通过 | ${body}`
    }
    if (body.includes('汇总')) {
      return `DryRun | 预检汇总 | ${body}`
    }
    if (body.includes('不可用') || body.includes('✗')) {
      return `DryRun | 读类工具预检失败 | ${body.replace('打听', 'checked')}`
    }
    if (body.includes('跳过')) return 'DryRun | 无 plan，跳过预检'
    return `DryRun | 读类工具预检 | ${body.replace('打听', 'checked')}`
  }

  if (raw.includes('[DryRun·恢复]')) {
    return `DryRun | 故障恢复链 | ${body}`
  }

  if (raw.includes('[Executor·回滚]')) {
    return `Compensator | 写类工具失败后执行回滚 | ${body}`
  }

  if (raw.includes('[Executor·提交]')) {
    if (body.includes('无可执行')) return 'Executor | 无可提交写类工具'
    if (body.includes('order_addon') || body.includes('deliver_to_poi_id')) {
      return `Executor | 写类工具提交成功 | addon delivery anchored | ${body}`
    }
    return `Executor | 写类工具提交 | ${body}`
  }

  if (raw.includes('[Executor·交付]')) {
    if (body.includes('跳过')) return 'Notifier | 缺少 plan/profile，跳过交付'
    return `Notifier | SummaryCard 生成完成 | ${body}`
  }

  if (/✗|失败|409|满座|冲突/i.test(raw)) {
    return `System | Exception Signal | ${body}`
  }

  return `System | ${body}`
}

export function humanizeTraceLines(lines: string[]): string[] {
  return lines.map(humanizeTraceLine)
}
