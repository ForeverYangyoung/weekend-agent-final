import { useState, useRef, useEffect, useCallback } from 'react'
import type {
  ChatMessage,
  DisplayPlan,
  PreferenceConflict,
  ProfileChip,
  ProfileOverride,
  ProgressStep,
  SSEEvent,
} from './types'
import { confirmAgent, replanAgent, streamAgent } from './api'
import { mapPlansFromBackend } from './mapPlans'
import { SCENARIO_PRESETS, type ScenarioId } from './scenarioPresets'
import { InputBar } from './components/InputBar'
import { WelcomeScreen } from './components/WelcomeScreen'
import { ProgressIndicator } from './components/ProgressIndicator'
import { PlanCards } from './components/PlanCards'
import { PreferencePanel } from './components/PreferencePanel'
import { ProfileChips } from './components/ProfileChips'
import { ScenarioSetup } from './components/ScenarioSetup'
import { TracePanel } from './components/TracePanel'
import { uiTraceLine } from './traceUi'

const DEFAULT_PANEL_PREFS = {
  distance: '5公里内',
  diet: '重口味',
  vibe: '轻松社交',
}

const INITIAL_MESSAGES: ChatMessage[] = [
  {
    id: 'welcome',
    role: 'ai',
    type: 'welcome',
    text:
      '嗨，我是你的周末小助手。\n\n答辩演示：左侧对话规划，右侧实时 Trace。\n先选场景再规划；朋友局可看「未说禁辣却唤醒健康档案」的 Zero-Skill Mock（详见 Trace 历史档案行）。满意后确认下单。',
    timestamp: Date.now(),
  },
]

const TRACE_PROGRESS: Array<{ prefix: string; label: string }> = [
  { prefix: '[Profiler]', label: '正在理解您的出行画像…' },
  { prefix: '[Researcher', label: '正在召回并对比候选店…' },
  { prefix: '[Planner', label: '正在组合并对比方案…' },
  { prefix: '[TargetedResearcher', label: '正在补充顺路加餐…' },
  { prefix: '[Critic', label: '正在规则校验…' },
  { prefix: '[Executor·预检]', label: '正在预检票位与库存…' },
]

function genId() {
  return Math.random().toString(36).slice(2, 10)
}

function progressFromTrace(trace: string[]): ProgressStep[] {
  return TRACE_PROGRESS.map(({ prefix, label }) => ({
    label,
    done: trace.some((line) => line.includes(prefix)),
  }))
}

function chipLabelForOverride(override: ProfileOverride): string {
  if (override.key === 'district') return override.value
  if (override.key === 'budget_per_person') return `约 ¥${override.value}/人`
  if (override.key === 'people_count') return `${override.value} 人`
  if (override.key === 'distance_limit_km') return `≤ ${override.value} km`
  return override.value
}

function sceneChipForPeople(count: number): ProfileChip | null {
  if (count >= 3) {
    return { key: 'scene', label: '朋友', value: 'friends', source: 'utterance', editable: true }
  }
  if (count === 2) {
    return { key: 'scene', label: '情侣', value: 'couple', source: 'utterance', editable: true }
  }
  if (count === 1) {
    return { key: 'scene', label: '独自', value: 'solo', source: 'utterance', editable: true }
  }
  return null
}

function mergeProfileChips(prev: ProfileChip[], override: ProfileOverride): ProfileChip[] {
  let next = prev.filter((c) => {
    if (override.key === 'people_count') {
      return (
        c.key !== 'people_count'
        && c.key !== 'scene'
        && !(c.key === 'interests' && /^\d+人?$/.test(c.value))
      )
    }
    if (override.key === 'dietary' && override.action === 'set') return c.key !== 'dietary'
    if (override.key === 'interests' && override.action === 'set') return c.key !== 'interests'
    if (override.action === 'add') {
      return !(c.key === override.key && c.value === override.value)
    }
    if (override.action === 'set') {
      return c.key !== override.key
    }
    return true
  })

  const chip: ProfileChip = {
    key: override.key,
    label: chipLabelForOverride(override),
    value: override.value,
    source: 'utterance',
    editable: true,
  }
  next = [...next, chip]

  if (override.key === 'people_count') {
    const n = Number.parseInt(override.value, 10)
    const sceneChip = sceneChipForPeople(n)
    if (sceneChip) next = [...next.filter((c) => c.key !== 'scene'), sceneChip]
  }

  return next
}

function panelToOverrides(prefs: typeof DEFAULT_PANEL_PREFS): ProfileOverride[] {
  const km = prefs.distance.match(/(\d+)/)?.[1] ?? '8'
  return [
    { key: 'distance_limit_km', value: km, action: 'set' },
    { key: 'dietary', value: prefs.diet, action: 'set' },
    { key: 'interests', value: prefs.vibe, action: 'set' },
  ]
}

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>(INITIAL_MESSAGES)
  const [appState, setAppState] = useState<
    'idle' | 'scenario_setup' | 'streaming' | 'plans_displayed' | 'hil_editing' | 'confirmed'
  >('idle')
  const [activeScenario, setActiveScenario] = useState<ScenarioId | null>(null)
  const [progressSteps, setProgressSteps] = useState<ProgressStep[]>([])
  const [traceLines, setTraceLines] = useState<string[]>([])
  const [currentTraceStep, setCurrentTraceStep] = useState<string | null>(null)
  const [plans, setPlans] = useState<DisplayPlan[]>([])
  const [profileChips, setProfileChips] = useState<ProfileChip[]>([])
  const [pendingOverrides, setPendingOverrides] = useState<ProfileOverride[]>([])
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [inputDisabled, setInputDisabled] = useState(false)
  const [isReplanning, setIsReplanning] = useState(false)
  const [isPreferencePanelOpen, setIsPreferencePanelOpen] = useState(false)
  const [panelPreferences, setPanelPreferences] = useState(DEFAULT_PANEL_PREFS)
  const [preferenceConflicts, setPreferenceConflicts] = useState<PreferenceConflict[]>([])
  const [acceptedAlternatives, setAcceptedAlternatives] = useState<Set<string>>(new Set())
  const [selectedAddonsByPlan, setSelectedAddonsByPlan] = useState<Map<string, Set<string>>>(
    new Map(),
  )
  const messagesEndRef = useRef<HTMLDivElement>(null)

  function initSelectedAddons(mappedPlans: DisplayPlan[]) {
    setSelectedAddonsByPlan((prev) => {
      const next = new Map(prev)
      for (const p of mappedPlans) {
        if (!p.addons?.length) continue
        next.set(p.id, new Set(p.addons.map((a) => a.addon_id)))
      }
      return next
    })
  }

  function handleToggleAddon(planId: string, addonId: string, checked: boolean) {
    setSelectedAddonsByPlan((prev) => {
      const next = new Map(prev)
      const current = new Set(next.get(planId) ?? [])
      if (checked) {
        current.add(addonId)
      } else {
        current.delete(addonId)
      }
      next.set(planId, current)
      return next
    })
  }

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [])

  useEffect(() => {
    scrollToBottom()
  }, [messages, progressSteps, appState, profileChips, scrollToBottom])

  function addMessage(msg: Omit<ChatMessage, 'id' | 'timestamp'>) {
    const full: ChatMessage = { ...msg, id: genId(), timestamp: Date.now() }
    setMessages((prev) => [...prev, full])
    return full
  }

  function appendTrace(lines: string[]) {
    if (!lines.length) return
    setTraceLines((prev) => [...prev, ...lines])
  }

  function pushUiTrace(phase: string, message: string) {
    appendTrace([uiTraceLine(phase, message)])
  }

  function applyTraceDelta(delta: string[] | undefined, fullTrace?: string[]) {
    if (delta?.length) {
      appendTrace(delta)
    } else if (fullTrace?.length) {
      setTraceLines(fullTrace)
    }
    const merged = fullTrace ?? []
    if (merged.length) {
      setProgressSteps(progressFromTrace(merged))
    }
  }

  async function consumePlanningStream(events: AsyncGenerator<SSEEvent>) {
    let awaiting: SSEEvent | null = null
    let lastTrace: string[] = []

    for await (const ev of events) {
      if (ev.event === 'start') {
        setCurrentTraceStep(null)
      }
      if (ev.event === 'step') {
        if (ev.step) setCurrentTraceStep(ev.step)
        const full = ev.state?.trace ?? []
        lastTrace = full
        applyTraceDelta(ev.trace_delta, full)
      }
      if (ev.event === 'trace_delta' && ev.lines?.length) {
        appendTrace(ev.lines)
        lastTrace = [...lastTrace, ...ev.lines]
        setProgressSteps(progressFromTrace(lastTrace))
      }
      if (ev.event === 'state' && ev.state?.trace) {
        lastTrace = ev.state.trace
        setTraceLines(lastTrace)
        setProgressSteps(progressFromTrace(lastTrace))
      }
      if (ev.event === 'awaiting_confirm') {
        awaiting = ev
        setCurrentTraceStep('awaiting_confirm')
        const planNames = (ev.plans ?? [])
          .map((p) => p.title ?? p.id)
          .join(' | ')
        pushUiTrace(
          '就绪',
          `左侧将展示 ${ev.plans?.length ?? 0} 套方案，请用户确认：${planNames}`,
        )
      }
      if (ev.event === 'error') {
        throw new Error(ev.message ?? '规划失败')
      }
    }

    if (!awaiting?.session_id || !awaiting.plans?.length) {
      throw new Error('未收到可确认的方案，请重试')
    }

    setSessionId(awaiting.session_id)
    setProfileChips(awaiting.profile_chips ?? [])
    setPreferenceConflicts(awaiting.preference_conflicts ?? [])
    setAcceptedAlternatives(new Set())
    setPendingOverrides([])
    setActiveScenario(null)
    const mappedPlans = mapPlansFromBackend(awaiting.plans)
    setPlans(mappedPlans)
    initSelectedAddons(mappedPlans)
    setProgressSteps(progressFromTrace(lastTrace).map((s) => ({ ...s, done: true })))

    const chipText = (awaiting.profile_chips ?? []).map((c) => c.label).join('、')
    const primary = awaiting.plans[0]
    const primaryIssue = primary?.planIssues?.[0]
    const conflictHint =
      (awaiting.preference_conflicts ?? []).length > 0
        ? '检测到「历史档案约束」和「当前显式偏好」冲突，请在上方标签里删除一边后再规划。'
        : ''
    const cuisineHint =
      primaryIssue?.code === 'cuisine_unavailable'
        ? primaryIssue.detail
        : primaryIssue?.code === 'cuisine_not_matched_but_nearby'
          ? primaryIssue.detail
          : ''
    const planMsg = addMessage({
      role: 'ai',
      type: 'plans',
      text: conflictHint
        || cuisineHint
        || (chipText
          ? `已按约束（${chipText}）筛出 ${awaiting.plans.length} 套不同店组合。绿标是命中说明；若指定菜系附近没有店，卡片会写明距离原因。`
          : '预检完成！下方是真实候选方案。可点标签修改偏好后重搜，满意再点「选这个」确认下单。'),
    })
    planMsg.plans = mapPlansFromBackend(awaiting.plans)

    setAppState('plans_displayed')
    setInputDisabled(false)
    setIsReplanning(false)
  }

  function handleScenarioSelect(id: ScenarioId) {
    if (inputDisabled) return
    const preset = SCENARIO_PRESETS[id]
    setActiveScenario(id)
    pushUiTrace('场景', `用户选择 ${preset.title}（${preset.subtitle}）`)
    setProfileChips([...preset.defaultChips])
    setPendingOverrides([])
    setPanelPreferences(preset.panelPrefs)
    setPreferenceConflicts([])
    setAppState('scenario_setup')
    addMessage({
      role: 'user',
      type: 'text',
      text: `选择场景：${preset.title}`,
    })
  }

  function handleCancelScenario() {
    setActiveScenario(null)
    setProfileChips([])
    setPendingOverrides([])
    setAppState('idle')
  }

  async function handleStartScenarioPlanning() {
    if (!activeScenario || inputDisabled) return
    const preset = SCENARIO_PRESETS[activeScenario]
    const dietLabels = profileChips.filter((c) => c.key === 'dietary').map((c) => c.label)
    const extra = dietLabels.length ? `，饮食：${dietLabels.join('、')}` : ''

    addMessage({
      role: 'user',
      type: 'text',
      text: `开始规划：${preset.title}${extra}`,
    })
    setAppState('streaming')
    setInputDisabled(true)
    setProgressSteps(TRACE_PROGRESS.map((t) => ({ label: t.label, done: false })))
    setCurrentTraceStep(null)
    pushUiTrace('触发', `开始规划 · ${preset.title}${extra}`)
    setPreferenceConflicts([])
    setAcceptedAlternatives(new Set())
    setSessionId(null)

    try {
      await consumePlanningStream(
        streamAgent(preset.basePrompt, null, pendingOverrides),
      )
    } catch (err) {
      setProgressSteps([])
      setAppState('scenario_setup')
      setInputDisabled(false)
      addMessage({
        role: 'ai',
        type: 'text',
        text: `抱歉，规划过程中出现了问题：${err instanceof Error ? err.message : '未知错误'}。请调整偏好后重试。`,
      })
    }
  }

  function handleSend(text: string) {
    if (!text.trim() || inputDisabled) return

    addMessage({ role: 'user', type: 'text', text: text.trim() })
    setAppState('streaming')
    setInputDisabled(true)
    setProgressSteps(TRACE_PROGRESS.map((t) => ({ label: t.label, done: false })))
    setPendingOverrides([])
    setPreferenceConflicts([])
    setAcceptedAlternatives(new Set())
    setActiveScenario(null)
    setSessionId(null)
    setCurrentTraceStep(null)
    pushUiTrace('触发', `自由输入规划：${text.trim().slice(0, 48)}`)

    runInitialStream(text.trim())
  }

  async function runInitialStream(userInput: string) {
    try {
      await consumePlanningStream(streamAgent(userInput))
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

  function handleRemoveChip(override: ProfileOverride) {
    pushUiTrace('偏好', `移除标签 ${override.key}=${override.value}`)
    setPendingOverrides((prev) => [...prev, override])
    setProfileChips((prev) =>
      prev.filter((c) => !(c.key === override.key && c.value === override.value)),
    )
    if (override.key === 'dietary') {
      setPreferenceConflicts((prev) =>
        prev.filter((c) => !c.conflictingTags?.includes(override.value)),
      )
    }
    if (appState === 'plans_displayed') setAppState('hil_editing')
  }

  function handleAddChip(override: ProfileOverride) {
    pushUiTrace('偏好', `添加标签 ${override.key}=${override.value}`)
    setPendingOverrides((prev) => [...prev, override])
    setProfileChips((prev) => mergeProfileChips(prev, override))
    if (override.key === 'dietary' && override.value) {
      setPreferenceConflicts((prev) => {
        if (!prev.length) return prev
        return prev.filter((c) => !c.conflictingTags?.includes(override.value))
      })
    }
    if (appState === 'plans_displayed') setAppState('hil_editing')
  }

  async function runReplanStream(overrides: ProfileOverride[], userText: string) {
    if (!sessionId) return

    setAppState('streaming')
    setInputDisabled(true)
    setIsReplanning(true)
    setProgressSteps(TRACE_PROGRESS.map((t) => ({ label: t.label, done: false })))
    setCurrentTraceStep(null)
    pushUiTrace('重规划', userText)
    setPendingOverrides(overrides)

    addMessage({ role: 'user', type: 'text', text: userText })

    try {
      await consumePlanningStream(replanAgent(sessionId, overrides))
    } catch (err) {
      setProgressSteps([])
      setAppState('hil_editing')
      setInputDisabled(false)
      setIsReplanning(false)
      addMessage({
        role: 'ai',
        type: 'text',
        text: `重规划失败：${err instanceof Error ? err.message : '未知错误'}`,
      })
    }
  }

  async function handleReplan() {
    const text =
      pendingOverrides.length > 0
        ? `按新偏好重规划（${pendingOverrides.length} 项调整）`
        : '重新规划'
    await runReplanStream(pendingOverrides, text)
  }

  async function handleConfirmPlan(planId: string, selectedAddonIds: string[] = []) {
    if (!sessionId) return
    const plan = plans.find((p) => p.id === planId)
    if (!plan) return

    setInputDisabled(true)
    const addonHint =
      selectedAddonIds.length > 0
        ? `，附加项 ${selectedAddonIds.length} 项`
        : plan.addons?.length
          ? '，未选附加项'
          : ''
    pushUiTrace('确认', `用户选定方案：${plan.venueChain}（${plan.title}）${addonHint}`)
    addMessage({
      role: 'user',
      type: 'text',
      text: `确认选择：${plan.title}`,
    })

    try {
      const result = await confirmAgent(sessionId, planId, selectedAddonIds)
      setCurrentTraceStep('executor')
      if (result.trace_tail?.length) {
        appendTrace(result.trace_tail)
      } else if (result.trace?.length) {
        appendTrace(result.trace)
      }

      const orderLines = result.orders
        .map((o) => `✅ ${o.stage} 已下单 · 订单号 ${o.order_id}`)
        .join('\n')

      addMessage({
        role: 'ai',
        type: 'text',
        text: `好的！已为您确认「${plan.title}」并完成下单。\n\n${orderLines || '（无订单回执）'}\n\n${result.summary_card?.share_text ?? ''}`,
      })
      setAppState('confirmed')
    } catch (err) {
      setInputDisabled(false)
      addMessage({
        role: 'ai',
        type: 'text',
        text: `下单失败：${err instanceof Error ? err.message : '未知错误'}`,
      })
    }
  }

  async function handlePreferenceSubmit(prefs: typeof DEFAULT_PANEL_PREFS) {
    setIsPreferencePanelOpen(false)
    const overrides = panelToOverrides(prefs)

    if (!sessionId) {
      if (activeScenario) {
        setProfileChips((prev) =>
          overrides.reduce((chips, o) => mergeProfileChips(chips, o), prev),
        )
        setPendingOverrides((prev) => [...prev, ...overrides])
        return
      }
      handleSend(
        `帮我安排周末出行。距离${prefs.distance}，想吃${prefs.diet}，氛围${prefs.vibe}。`,
      )
      return
    }

    setProfileChips((prev) =>
      overrides.reduce((chips, o) => mergeProfileChips(chips, o), prev),
    )
    await runReplanStream(overrides, `按面板调整偏好（${prefs.diet} · ${prefs.distance}）`)
  }

  function handleAcceptAlternative(planId: string) {
    const plan = plans.find((p) => p.id === planId)
    if (plan) {
      pushUiTrace('替代', `用户接受就近替代：${plan.venueChain}`)
    }
    setAcceptedAlternatives((prev) => new Set([...prev, planId]))
    setAppState('plans_displayed')
  }

  function handleEditPreference() {
    setIsPreferencePanelOpen(true)
    setAppState('hil_editing')
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
      text: '没问题，请点改下方偏好标签（× 删除 / 添加新偏好），然后点「按新偏好重新规划」。',
    })
    setAppState('hil_editing')
  }

  const showChipEditor =
    (appState === 'hil_editing' || appState === 'plans_displayed') && !activeScenario
  const activePreset = activeScenario ? SCENARIO_PRESETS[activeScenario] : null

  return (
    <div className="demo-shell">
      <div className="demo-phone-col">
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
              <div className="header-subtitle">周末出游助手 · HIL 在线</div>
            </div>
          </div>

          <div className="chat-messages">
            {messages.map((msg) => {
              if (msg.type === 'welcome') {
                return (
                  <div key={msg.id} className="msg-row msg-ai">
                    <WelcomeScreen
                      greeting={msg.text ?? ''}
                      onScenarioSelect={handleScenarioSelect}
                      disabled={inputDisabled}
                    />
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
                        acceptedAlternatives={acceptedAlternatives}
                        selectedAddonsByPlan={selectedAddonsByPlan}
                        onConfirm={handleConfirmPlan}
                        onToggleAddon={handleToggleAddon}
                        onEditPreference={handleEditPreference}
                        onAcceptAlternative={handleAcceptAlternative}
                        onReject={handleRejectPlan}
                        disabled={appState === 'confirmed' || inputDisabled}
                      />
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

            {appState === 'scenario_setup' && activePreset && (
              <div className="msg-row msg-ai">
                <ScenarioSetup
                  preset={activePreset}
                  chips={profileChips}
                  onRemove={handleRemoveChip}
                  onAdd={handleAddChip}
                  onStart={handleStartScenarioPlanning}
                  onCancel={handleCancelScenario}
                  disabled={inputDisabled}
                />
              </div>
            )}

            {showChipEditor && preferenceConflicts.length > 0 && (
              <div className="msg-row msg-ai">
                <div className="preference-conflict-banner">
                  <div className="preference-conflict-kicker">未来方向预览 · Zero-Skill 隐式画像 Mock</div>
                  {preferenceConflicts.map((c, i) => (
                    <div key={i}>
                      <strong>{c.headline}</strong> {c.detail}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {showChipEditor && profileChips.length > 0 && (
              <div className="msg-row msg-ai">
                <ProfileChips
                  chips={profileChips}
                  editing={appState === 'hil_editing' || appState === 'plans_displayed'}
                  onRemove={handleRemoveChip}
                  onAdd={handleAddChip}
                  onReplan={handleReplan}
                  replanning={isReplanning}
                />
              </div>
            )}

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
                : appState === 'scenario_setup'
                  ? '或在上方补充偏好后点「按此偏好开始规划」'
                  : appState === 'hil_editing'
                    ? '或在上方修改偏好后点「重新规划」'
                    : '也可直接输入自由需求…'
            }
          />

          <PreferencePanel
            open={isPreferencePanelOpen}
            preferences={panelPreferences}
            onChange={setPanelPreferences}
            onClose={() => setIsPreferencePanelOpen(false)}
            onSubmit={handlePreferenceSubmit}
          />
        </div>
      </div>

      <div className="demo-trace-col">
        <TracePanel
          lines={traceLines}
          live={appState === 'streaming'}
          currentStep={currentTraceStep}
        />
      </div>
    </div>
  )
}
