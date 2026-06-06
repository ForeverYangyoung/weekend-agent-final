import { useState, useRef, useEffect, useCallback } from 'react'
import type { ChatMessage, DisplayPlan, DisplayTransit, PlanData, PlanStageData, PreferenceState, ProgressStep } from './types'
import { streamAgent, revisePlan } from './api'
import { InputBar } from './components/InputBar'
import { WelcomeScreen } from './components/WelcomeScreen'
import { ProgressIndicator } from './components/ProgressIndicator'
import { PlanCards } from './components/PlanCards'
import { PreferencePanel } from './components/PreferencePanel'

const INITIAL_MESSAGES: ChatMessage[] = [
  {
    id: 'welcome',
    role: 'ai',
    type: 'welcome',
    text: '嗨，我是你的周末小助手，今天又不知道去哪玩？告诉我同行人数，时间以及特殊需求，我就能为您计划和下单啦。',
    timestamp: Date.now(),
  },
]

const SUGGESTED_PROMPTS = [
  '我下午想和老婆孩子一起出去玩，时间大概在2点~5点，我和老婆正在减肥，找好吃晚餐的地方',
  '我今天想和三个大学同学一起出去玩，时间大概在2点~8点，工作了一周了，希望能在户外玩一玩',
]

function genId() {
  return Math.random().toString(36).slice(2, 10)
}

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>(INITIAL_MESSAGES)
  const [appState, setAppState] = useState<'idle' | 'streaming' | 'plans_displayed' | 'preferences' | 'confirmed'>('idle')
  const [progressSteps, setProgressSteps] = useState<ProgressStep[]>([])
  const [plans, setPlans] = useState<DisplayPlan[]>([])
  const [preferences, setPreferences] = useState<PreferenceState | null>(null)
  const [inputDisabled, setInputDisabled] = useState(false)

  // Revision state
  const [feedbackPlanId, setFeedbackPlanId] = useState<string | null>(null)
  const [revisionLoading, setRevisionLoading] = useState(false)
  const lastProfileRef = useRef<Record<string, unknown> | null>(null)
  const snapshotsRef = useRef<Map<string, Record<string, unknown>[]>>(new Map())

  const messagesEndRef = useRef<HTMLDivElement>(null)

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [])

  useEffect(() => {
    scrollToBottom()
  }, [messages, progressSteps, appState, scrollToBottom])

  function addMessage(msg: Omit<ChatMessage, 'id' | 'timestamp'>) {
    const full: ChatMessage = { ...msg, id: genId(), timestamp: Date.now() }
    setMessages((prev) => [...prev, full])
    return full
  }

  function handleSend(text: string) {
    if (!text.trim() || inputDisabled) return

    if (text.trim() === '选择') {
      handleChoiceMode()
      return
    }

    // If we're in plans_displayed state and user types feedback, treat as revision
    if (appState === 'plans_displayed' && plans.length > 0) {
      handleGlobalFeedback(text.trim())
      return
    }

    addMessage({ role: 'user', type: 'text', text: text.trim() })
    setAppState('streaming')
    setInputDisabled(true)
    setProgressSteps([
      { label: '正在为您寻找户外出行好去处……', done: false },
      { label: '正在为您寻找适合的餐厅……', done: false },
      { label: '正在为您寻找顺路小店……', done: false },
      { label: '正在为您规划行程……', done: false },
    ])

    runStream(text.trim())
  }

  async function runStream(userInput: string) {
    try {
      let stepIndex = 0
      const stepTimer = setInterval(() => {
        setProgressSteps((prev) => {
          const next = [...prev]
          if (stepIndex < next.length) {
            next[stepIndex] = { ...next[stepIndex], done: true }
            stepIndex++
          }
          return next
        })
      }, 800)

      let finalCard: { title?: string; share_text?: string; body_markdown?: string } | null = null
      let lastPlans: PlanData[] = []

      for await (const ev of streamAgent(userInput)) {
        if (ev.event === 'state' && ev.state) {
          if (ev.state.group_profile) {
            lastProfileRef.current = ev.state.group_profile
          }
          // Backend sends `plan` + `plan_alternatives`, not `plans`
          const s = ev.state
          const combined: PlanData[] = []
          if (s.plan) combined.push(s.plan as unknown as PlanData)
          if (s.plan_alternatives) combined.push(...(s.plan_alternatives as unknown as PlanData[]))
          if (combined.length > 0) lastPlans = combined
        }
        if (ev.event === 'final') {
          finalCard = ev.summary_card ?? null
          // Fallback: plan data from final event (in case state events were dropped by proxy)
          if (lastPlans.length === 0 && ev.plan) {
            const fb: PlanData[] = []
            fb.push(ev.plan as unknown as PlanData)
            if (ev.plan_alternatives) fb.push(...(ev.plan_alternatives as unknown as PlanData[]))
            lastPlans = fb
          }
        }
      }

      clearInterval(stepTimer)

      setProgressSteps((prev) => prev.map((s) => ({ ...s, done: true })))
      await new Promise((r) => setTimeout(r, 600))

      const displayPlans = buildDisplayPlans(lastPlans, finalCard, userInput)
      setPlans(displayPlans)

      const planMsg = addMessage({
        role: 'ai',
        type: 'plans',
        text: displayPlans.length > 0
          ? '已经为您找到计划，喜欢的话确认一下我就可以帮您点奶茶，买票，打车，订座啦'
          : '已经为您找到两种计划，喜欢的话确认一下我就可以帮您点奶茶，买票，打车，订座啦',
      })
      planMsg.plans = displayPlans

      setAppState('plans_displayed')
      setInputDisabled(false)
    } catch (err) {
      setProgressSteps([])
      setAppState('idle')
      setInputDisabled(false)
      addMessage({
        role: 'ai',
        type: 'text',
        text: `抱歉，规划过程中出现了问题：${err instanceof Error ? err.message : '未知错误'}。请重试一下。`,
      })
    }
  }

  // ── Revision handlers ──

  function handleStartModify(planId: string) {
    setFeedbackPlanId(planId)
  }

  function handleCancelModify() {
    setFeedbackPlanId(null)
  }

  async function handleSubmitFeedback(planId: string, feedback: string) {
    const plan = plans.find((p) => p.id === planId)
    if (!plan || !feedback.trim()) return

    const profile = lastProfileRef.current
    if (!profile) {
      addMessage({
        role: 'ai',
        type: 'text',
        text: '抱歉，无法获取您的偏好信息，请重新开始规划。',
      })
      return
    }

    setRevisionLoading(true)
    setFeedbackPlanId(null)

    const existingSnapshots = snapshotsRef.current.get(planId) ?? []

    try {
      const res = await revisePlan({
        plan: plan.rawPlan,
        profile,
        feedback: feedback.trim(),
        revision_round: existingSnapshots.length,
        revision_history: existingSnapshots,
        locked_stages: plan.lockedStages,
      })

      if (res.status === 'applied') {
        const revisedPlanData = res.updated_plan as unknown as PlanData
        const revisedDisplay = planDataToDisplay(
          revisedPlanData,
          planId,
          revisedPlanData as unknown as Record<string, unknown>,
        )

        // Store snapshots for future revisions
        snapshotsRef.current.set(planId, res.plan_snapshots)

        // Build regenerated alternatives
        const allDisplayPlans: DisplayPlan[] = [revisedDisplay]
        if (res.alternative_plans?.length > 0) {
          for (let i = 0; i < res.alternative_plans.length; i++) {
            const altData = res.alternative_plans[i] as unknown as PlanData
            allDisplayPlans.push(planDataToDisplay(altData, `plan_alt_${i + 1}`))
          }
        }

        setPlans(allDisplayPlans)

        // Show revision events
        if (res.plan_events.length > 0) {
          const eventsMsg = addMessage({
            role: 'ai',
            type: 'text',
            text:
              '已根据您的反馈调整方案：\n' +
              res.plan_events.map((e) => `  ✓ ${e.summary}`).join('\n'),
          })
          eventsMsg.planEvents = res.plan_events
        }

        // Show revised plans
        const plansMsg = addMessage({
          role: 'ai',
          type: 'plans',
          text: allDisplayPlans.length > 1
            ? '这是修改后的方案，还有重新生成的备选：'
            : '这是修改后的方案：',
        })
        plansMsg.plans = allDisplayPlans
      } else {
        addMessage({
          role: 'ai',
          type: 'text',
          text: '抱歉，无法应用您的修改建议。可能因为该阶段已被锁定，请尝试其他修改方式。',
        })
      }
    } catch (err) {
      addMessage({
        role: 'ai',
        type: 'text',
        text: `修改失败：${err instanceof Error ? err.message : '未知错误'}`,
      })
    } finally {
      setRevisionLoading(false)
    }
  }

  async function handleGlobalFeedback(feedback: string) {
    // Apply feedback to the first plan (most common case)
    if (plans.length === 0) return

    addMessage({ role: 'user', type: 'text', text: feedback })
    const planId = plans[0].id

    const plan = plans[0]
    const profile = lastProfileRef.current
    if (!profile) {
      addMessage({
        role: 'ai',
        type: 'text',
        text: '抱歉，无法获取您的偏好信息，请重新开始规划。',
      })
      return
    }

    setRevisionLoading(true)
    const existingSnapshots = snapshotsRef.current.get(planId) ?? []

    try {
      const res = await revisePlan({
        plan: plan.rawPlan,
        profile,
        feedback,
        revision_round: existingSnapshots.length,
        revision_history: existingSnapshots,
        locked_stages: plan.lockedStages,
      })

      if (res.status === 'applied') {
        const revisedPlanData = res.updated_plan as unknown as PlanData
        const revisedDisplay = planDataToDisplay(
          revisedPlanData, planId,
          revisedPlanData as unknown as Record<string, unknown>,
        )

        snapshotsRef.current.set(planId, res.plan_snapshots)

        // Build regenerated alternatives
        const allDisplayPlans: DisplayPlan[] = [revisedDisplay]
        if (res.alternative_plans?.length > 0) {
          for (let i = 0; i < res.alternative_plans.length; i++) {
            const altData = res.alternative_plans[i] as unknown as PlanData
            allDisplayPlans.push(planDataToDisplay(altData, `plan_alt_${i + 1}`))
          }
        }

        setPlans(allDisplayPlans)

        if (res.plan_events.length > 0) {
          const eventsMsg = addMessage({
            role: 'ai',
            type: 'text',
            text:
              '已根据您的反馈调整方案：\n' +
              res.plan_events.map((e) => `  ✓ ${e.summary}`).join('\n'),
          })
          eventsMsg.planEvents = res.plan_events
        }

        // Re-display updated plans
        const plansMsg = addMessage({
          role: 'ai',
          type: 'plans',
          text: allDisplayPlans.length > 1
            ? '这是修改后的方案，还有重新生成的备选：'
            : '这是修改后的方案，您看看满意吗？',
        })
        plansMsg.plans = allDisplayPlans
      } else {
        addMessage({
          role: 'ai',
          type: 'text',
          text: '抱歉，无法应用您的修改建议。被锁定的阶段无法修改，请尝试其他方式。',
        })
      }
    } catch (err) {
      addMessage({
        role: 'ai',
        type: 'text',
        text: `修改失败：${err instanceof Error ? err.message : '未知错误'}`,
      })
    } finally {
      setRevisionLoading(false)
    }
  }

  // ── Choice / Preference mode ──

  function handleChoiceMode() {
    addMessage({ role: 'user', type: 'text', text: '选择' })
    const initialPrefs: PreferenceState = {
      foodTags: [
        { id: 'korean', label: '韩式', emoji: '🇰🇷', selected: false, recommended: true },
        { id: 'thai', label: '泰味', emoji: '🇹🇭', selected: false, recommended: false },
        { id: 'sichuan', label: '川麻', emoji: '🌶️', selected: false, recommended: false },
        { id: 'fresh', label: '鲜香', emoji: '🦐', selected: false, recommended: false },
        { id: 'sweet', label: '酸甜', emoji: '🍋', selected: false, recommended: false },
      ],
      activityTags: [
        { id: 'photo', label: '拍照打卡', emoji: '📸', selected: false, recommended: true },
        { id: 'outdoor', label: '户外运动', emoji: '🏃', selected: false, recommended: false },
        { id: 'indoor', label: '室内休闲', emoji: '🎮', selected: false, recommended: false },
        { id: 'culture', label: '文化展览', emoji: '🎨', selected: false, recommended: false },
        { id: 'shopping', label: '逛逛街', emoji: '🛍️', selected: false, recommended: false },
      ],
      priorities: [
        { id: 'transport', label: '交通', emoji: '🚗', order: 0 },
        { id: 'food', label: '美食', emoji: '🍜', order: 1 },
        { id: 'scenery', label: '风景', emoji: '🏞️', order: 2 },
        { id: 'entertainment', label: '娱乐', emoji: '🎯', order: 3 },
        { id: 'price', label: '价格', emoji: '💰', order: 4 },
      ],
    }
    setPreferences(initialPrefs)

    addMessage({
      role: 'ai',
      type: 'preferences',
      text: '今天的胃口适合遇见谁？让我来规划，你来保持放松好心情！请选择你的偏好排序：',
    })

    setAppState('preferences')
  }

  function handleConfirmPlan(planId: string) {
    const plan = plans.find((p) => p.id === planId)
    if (!plan) return

    addMessage({
      role: 'user',
      type: 'text',
      text: `确认选择：${plan.title}`,
    })
    addMessage({
      role: 'ai',
      type: 'text',
      text: `好的！已为您确认「${plan.title}」。正在为您下单……\n\n✅ 门票已购买\n✅ 餐厅已订座\n✅ 奶茶已下单\n\n祝您周末愉快！🎉`,
    })
    setAppState('confirmed')
    setInputDisabled(true)
  }

  function handleRejectPlan() {
    addMessage({
      role: 'user',
      type: 'text',
      text: '不喜欢这些方案',
    })
    addMessage({
      role: 'ai',
      type: 'text',
      text: '如果都不喜欢也可以补充更详细的偏好信息，我为您重新规划。比如告诉我：\n• 想去哪个区？\n• 有没有特别想吃的菜系？\n• 预算大概多少？\n\n或者直接对某个方案提修改意见，比如"公园不错别动，餐厅换一个日料"。',
    })
    setAppState('idle')
  }

  function handlePreferencesConfirm() {
    setAppState('streaming')
    setInputDisabled(true)
    setProgressSteps([
      { label: '正在根据您的偏好寻找游玩地点……', done: false },
      { label: '正在匹配合适的餐厅……', done: false },
      { label: '正在规划最优路线……', done: false },
      { label: '正在生成方案……', done: false },
    ])

    let step = 0
    const timer = setInterval(() => {
      setProgressSteps((prev) => {
        const next = [...prev]
        if (step < next.length) {
          next[step] = { ...next[step], done: true }
          step++
        }
        return next
      })
      if (step >= 4) {
        clearInterval(timer)
        finishPreferencePlanning()
      }
    }, 700)
  }

  function finishPreferencePlanning() {
    // Re-run the stream with a preference-based prompt
    addMessage({ role: 'user', type: 'text', text: '根据偏好重新规划' })
    setAppState('streaming')
    runStream('根据偏好重新规划')
  }

  return (
    <div className="app-container">
      <div className="app-phone">
        <div className="status-bar">
          <span className="status-time">9:41</span>
          <div className="status-icons">
            <svg width="17" height="11" viewBox="0 0 17 11"><rect x="0" y="0" width="15" height="11" rx="2" fill="none" stroke="#222" strokeWidth="0.8"/><rect x="2" y="2" width="11" height="7" rx="1" fill="#222"/></svg>
          </div>
        </div>

        <div className="chat-header">
          <div className="header-avatar">W</div>
          <div>
            <div className="header-title">Weekend Agent</div>
            <div className="header-subtitle">周末出游助手 · 在线</div>
          </div>
        </div>

        <div className="chat-messages">
          {messages.map((msg) => {
            if (msg.type === 'welcome') {
              return (
                <div key={msg.id} className="msg-row msg-ai">
                  <WelcomeScreen
                    greeting={msg.text ?? ''}
                    prompts={SUGGESTED_PROMPTS}
                    onPromptClick={handleSend}
                    disabled={inputDisabled}
                  />
                </div>
              )
            }

            if (msg.type === 'progress') {
              return (
                <div key={msg.id} className="msg-row msg-ai">
                  <ProgressIndicator steps={msg.progressSteps ?? []} />
                </div>
              )
            }

            if (msg.type === 'plans' && msg.plans) {
              return (
                <div key={msg.id} className="msg-row msg-ai msg-plan-row">
                  <div className="ai-bubble ai-bubble-plan">
                    <div className="bubble-text">{msg.text}</div>
                    <PlanCards
                      plans={msg.plans}
                      onConfirm={handleConfirmPlan}
                      onReject={handleRejectPlan}
                      onModify={handleStartModify}
                      onSubmitFeedback={handleSubmitFeedback}
                      onCancelModify={handleCancelModify}
                      feedbackPlanId={feedbackPlanId}
                      revisionLoading={revisionLoading}
                      disabled={appState === 'confirmed'}
                    />
                  </div>
                </div>
              )
            }

            if (msg.type === 'preferences') {
              return (
                <div key={msg.id} className="msg-row msg-ai msg-pref-row">
                  <div className="ai-bubble ai-bubble-pref">
                    <div className="bubble-text">{msg.text}</div>
                    {preferences && (
                      <PreferencePanel
                        preferences={preferences}
                        onChange={setPreferences}
                        onConfirm={handlePreferencesConfirm}
                      />
                    )}
                  </div>
                </div>
              )
            }

            if (msg.role === 'user') {
              return (
                <div key={msg.id} className="msg-row msg-user">
                  <div className="user-bubble">{msg.text}</div>
                </div>
              )
            }

            return (
              <div key={msg.id} className="msg-row msg-ai">
                <div className="ai-bubble">
                  <div className="bubble-text">{msg.text}</div>
                </div>
              </div>
            )
          })}

          {appState === 'streaming' && progressSteps.length > 0 && (
            <div className="msg-row msg-ai">
              <ProgressIndicator steps={progressSteps} live />
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        <InputBar
          onSend={handleSend}
          disabled={inputDisabled}
          placeholder={
            appState === 'confirmed'
              ? '已确认，祝您周末愉快！'
              : appState === 'preferences'
                ? '在上方选择偏好，或补充更多信息...'
                : appState === 'plans_displayed'
                  ? '输入修改建议，如"公园不错别动，餐厅换个日料"...'
                  : '说说你的需求，比如几个人、什么时间、想去哪...'
          }
        />
      </div>
    </div>
  )
}

// ── Plan data parsing ──

function findStage(plan: PlanData, name: string) {
  return plan.stages.find((s) => s.name === name)
}

function parseTime(t: string): number {
  const parts = t.split(':')
  return parseInt(parts[0], 10) * 60 + parseInt(parts[1], 10)
}

function computeTransits(stages: PlanStageData[]) {
  const transits: DisplayTransit[] = []
  const sorted = [...stages].sort((a, b) => parseTime(a.start_time) - parseTime(b.start_time))

  for (let i = 0; i < sorted.length - 1; i++) {
    const cur = sorted[i]
    const nxt = sorted[i + 1]
    const curEnd = parseTime(cur.end_time)
    const nxtStart = parseTime(nxt.start_time)
    const gap = nxtStart - curEnd
    if (gap > 0) {
      const distKm = nxt.primary.metadata?.distance_km as number | undefined
      transits.push({
        from: cur.primary.name,
        to: nxt.primary.name,
        startTime: cur.end_time,
        endTime: nxt.start_time,
        durationMin: gap,
        distanceKm: distKm ?? undefined,
        mode: distKm && distKm > 1 ? '打车' : '步行',
      })
    }
  }
  return transits
}

function planDataToDisplay(
  plan: PlanData,
  id: string,
  rawPlan?: Record<string, unknown>,
): DisplayPlan {
  const play = findStage(plan, '玩')
  const eat = findStage(plan, '吃')
  const addon = findStage(plan, '加餐')

  return {
    id,
    title: plan.summary || '推荐方案',
    play: {
      name: play?.primary.name ?? '待定',
      time: play ? `${play.start_time}-${play.end_time}` : '',
      startTime: play?.start_time ?? '',
      endTime: play?.end_time ?? '',
      desc: play?.primary.reason || play?.primary.category || '',
      tags: (play?.primary.metadata?.tags as string[]) ?? [],
      meta: play?.primary.metadata,
    },
    eat: {
      name: eat?.primary.name ?? '待定',
      time: eat ? `${eat.start_time}-${eat.end_time}` : '',
      startTime: eat?.start_time ?? '',
      endTime: eat?.end_time ?? '',
      desc: eat?.primary.reason || eat?.primary.category || '',
      tags: (eat?.primary.metadata?.tags as string[]) ?? [],
      meta: eat?.primary.metadata,
    },
    addon: addon
      ? {
          name: addon.primary.name,
          time: `${addon.start_time}-${addon.end_time}`,
          startTime: addon.start_time,
          endTime: addon.end_time,
          desc: addon.primary.reason || addon.primary.category,
          tags: (addon.primary.metadata?.tags as string[]) ?? [],
          meta: addon.primary.metadata,
        }
      : undefined,
    transits: computeTransits(plan.stages),
    totalPrice:
      plan.total_cost_estimate > 0
        ? `¥${plan.total_cost_estimate}/人`
        : '待估算',
    score: Math.round(plan.score),
    highlights: plan.stages
      .filter((s) => s.primary.reason)
      .map((s) => s.primary.reason),
    lockedStages: plan.locked_stages ?? [],
    version: plan.version ?? 1,
    rawPlan: rawPlan ?? (plan as unknown as Record<string, unknown>),
  }
}

function buildDisplayPlans(
  backendPlans: PlanData[],
  card: { title?: string; share_text?: string; body_markdown?: string } | null,
  _userInput: string,
): DisplayPlan[] {
  if (backendPlans.length > 0) {
    return backendPlans.map((plan, i) =>
      planDataToDisplay(plan, `plan_${i + 1}`),
    )
  }

  function mkStage(name: string, start: string, end: string, desc: string, tags: string[]) {
    return { name, time: `${start}-${end}`, startTime: start, endTime: end, desc, tags }
  }

  // Fallback: backend returned no plans — generate mock display plans
  if (card?.body_markdown) {
    return [
      {
        id: 'plan_1',
        title: card.title || '推荐方案 A',
        play: mkStage('户外游玩', '14:00', '16:30', '根据您的偏好推荐', ['户外', '推荐']),
        eat: mkStage('精选餐厅', '17:00', '18:30', '匹配您的口味', ['美食', '人气']),
        addon: mkStage('顺路奶茶', '16:30', '16:45', '休息一下', ['饮品']),
        transits: [
          { from: '户外游玩', to: '顺路奶茶', startTime: '16:30', endTime: '16:30', durationMin: 0, mode: '步行' },
          { from: '顺路奶茶', to: '精选餐厅', startTime: '16:45', endTime: '17:00', durationMin: 15, mode: '打车' },
        ],
        totalPrice: '¥298/人',
        score: 92,
        highlights: ['评分高', '顺路方便'],
        lockedStages: [],
        version: 1,
        rawPlan: {},
      },
      {
        id: 'plan_2',
        title: card.title ? `${card.title} B` : '推荐方案 B',
        play: mkStage('城市漫步', '14:30', '17:00', '轻松休闲路线', ['休闲', '城市']),
        eat: mkStage('人气美食', '17:30', '19:00', '高评分餐厅', ['口碑', '地道']),
        transits: [
          { from: '城市漫步', to: '人气美食', startTime: '17:00', endTime: '17:30', durationMin: 30, mode: '打车' },
        ],
        totalPrice: '¥228/人',
        score: 87,
        highlights: ['性价比高', '路线顺畅'],
        lockedStages: [],
        version: 1,
        rawPlan: {},
      },
    ]
  }

  return [
    {
      id: 'plan_1',
      title: '方案 A · 城市探索',
      play: mkStage('南湖公园 · 泛舟游湖', '14:00', '16:30', '湖面泛舟，绿道骑行，享受户外阳光', ['户外', '运动', '推荐']),
      eat: mkStage('隐溪·湖畔餐厅', '17:00', '18:30', '低卡轻食，湖畔景观位', ['轻食', '景观', '健康']),
      addon: mkStage('喜茶 · 南湖店', '16:30', '16:45', '顺路自提，新品多肉葡萄', ['饮品', '顺路']),
      transits: [
        { from: '南湖公园', to: '喜茶', startTime: '16:30', endTime: '16:30', durationMin: 0, mode: '步行' },
        { from: '喜茶', to: '隐溪·湖畔餐厅', startTime: '16:45', endTime: '17:00', durationMin: 15, mode: '打车' },
      ],
      totalPrice: '¥298/人',
      score: 92,
      highlights: ['风景优美', '餐厅健康低卡', '行程顺路不绕'],
      lockedStages: [],
      version: 1,
      rawPlan: {},
    },
    {
      id: 'plan_2',
      title: '方案 B · 文艺漫游',
      play: mkStage('东山文创园 · 艺术展览', '14:30', '17:00', '网红打卡地，艺术展览+手作体验', ['文艺', '打卡', '室内']),
      eat: mkStage('老街坊·私房菜', '17:30', '19:00', '地道本帮菜，人均亲民', ['地道', '口碑']),
      addon: mkStage('瑞幸咖啡 · 文创店', '17:00', '17:15', '园区内，逛累了来一杯', ['咖啡', '便利']),
      transits: [
        { from: '东山文创园', to: '瑞幸咖啡', startTime: '17:00', endTime: '17:00', durationMin: 0, mode: '步行' },
        { from: '瑞幸咖啡', to: '老街坊·私房菜', startTime: '17:15', endTime: '17:30', durationMin: 15, mode: '打车' },
      ],
      totalPrice: '¥228/人',
      score: 87,
      highlights: ['拍照出片', '性价比高', '交通便利'],
      lockedStages: [],
      version: 1,
      rawPlan: {},
    },
  ]
}
