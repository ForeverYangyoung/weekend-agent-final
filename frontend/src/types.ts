/** SSE event from the backend streaming endpoint */
export interface SSEEvent {
  event: 'start' | 'state' | 'step' | 'trace_delta' | 'final' | 'awaiting_confirm' | 'done' | 'error'
  user_input?: string
  session_id?: string
  replan?: boolean
  force_failure?: string | null
  step?: string
  trace_delta?: string[]
  lines?: string[]
  note?: string
  state?: AgentStatePayload
  summary?: SummaryPayload
  summary_card?: SummaryCard
  profile_chips?: ProfileChip[]
  preference_conflicts?: PreferenceConflict[]
  plans?: BackendPlanPayload[]
  dry_run_calls?: unknown[]
  message?: string
}

export interface ProfileChip {
  key: string
  label: string
  value: string
  confidence?: number
  editable?: boolean
  source?: string
}

export interface ProfileOverride {
  key: string
  value: string
  action: 'add' | 'remove' | 'set'
}

export type PlanIssueKind = 'ok' | 'needs_preference_fix' | 'alternative_available' | 'blocked'

export interface PlanIssue {
  code: string
  headline: string
  detail: string
  suggestions?: string[]
  allowAcceptAlternative?: boolean
  missingCuisine?: string
  playArea?: string
}

export interface PreferenceConflict {
  code: string
  headline: string
  detail: string
  suggestions?: string[]
  conflictingTags?: string[]
}

export interface BackendPlanPayload {
  id: string
  title: string
  order_label?: string
  score?: number
  totalPrice?: string
  activeConstraints?: string[]
  highlights?: string[]
  matchReasons?: string[]
  planIssues?: PlanIssue[]
  issueKind?: PlanIssueKind
  allowAcceptAlternative?: boolean
  constraintIssues?: string[]
  isValid?: boolean
  isCompromised?: boolean
  compromiseMessage?: string
  compromiseSource?: string
  diffSummary?: string
  play?: { name: string; time: string; desc: string; tags: string[]; priceLabel?: string; distanceLabel?: string }
  eat?: { name: string; time: string; desc: string; tags: string[]; priceLabel?: string; distanceLabel?: string }
  addon?: { name: string; desc: string; tags: string[]; priceLabel?: string; distanceLabel?: string }
  addons?: Array<{
    addon_id: string
    type?: string
    description: string
    price: number
    target_poi_id?: string
  }>
}

export interface AgentStatePayload {
  user_input?: string
  trace?: string[]
  group_profile?: {
    scene?: string
    people_count?: number
    kids_ages?: number[]
    start_time?: string
    duration_h?: number
    distance_limit_km?: number
    dietary_tags?: string[]
    interests?: string[]
    budget?: string
    [key: string]: unknown
  }
  plans?: PlanPayload[]
  plan_iteration?: number
  executed_calls?: unknown[]
  failed_calls?: unknown[]
}

export interface PlanPayload {
  stage_order?: string[]
  play?: PlanStage
  eat?: PlanStage
  addon?: PlanStage
  total_budget?: number
  score?: number
}

export interface PlanStage {
  poi_name?: string
  poi_id?: string
  category?: string
  booking_ref?: string
  price?: number
  lat?: number
  lng?: number
  tags?: string[]
  duration_min?: number
}

export interface SummaryPayload {
  scene?: string
  plan_iteration?: number
  executed?: number
  failed?: number
}

export interface SummaryCard {
  title?: string
  share_text?: string
  body_markdown?: string
}

/** Frontend message model for the chat UI */
export interface ChatMessage {
  id: string
  role: 'ai' | 'user'
  type: 'text' | 'progress' | 'plans' | 'preferences' | 'welcome'
  text?: string
  plans?: DisplayPlan[]
  progressSteps?: ProgressStep[]
  preferences?: PreferenceState
  planEvents?: Array<{ event_type: string; summary: string; timestamp?: string; version?: number }>
  timestamp: number
}

export interface PlanVenue {
  name: string
  time: string
  desc: string
  tags: string[]
  priceLabel?: string
  distanceLabel?: string
}

export interface PlanTimelineItem {
  kind: 'play' | 'eat' | 'addon'
  label: string
  time: string
  name: string
  desc: string
  priceLabel?: string
  distanceLabel?: string
  tags: string[]
}

export interface PlanAddon {
  addon_id: string
  type?: string
  description: string
  price: number
  target_poi_id?: string
}

export interface DisplayPlan {
  id: string
  title: string
  orderLabel: string
  venueChain: string
  diffSummary: string
  activeConstraints: string[]
  play: PlanVenue
  eat: PlanVenue
  addon?: { name: string; desc: string; tags: string[] }
  addons?: PlanAddon[]
  timeline: PlanTimelineItem[]
  totalPrice: string
  score: number
  highlights: string[]
  matchReasons: string[]
  planIssues: PlanIssue[]
  issueKind: PlanIssueKind
  allowAcceptAlternative: boolean
  constraintIssues: string[]
  isValid: boolean
  isCompromised?: boolean
  compromiseMessage?: string
  compromiseSource?: string
}

export interface PanelPreferences {
  distance: string
  diet: string
  vibe: string
}

export interface ProgressStep {
  label: string
  done: boolean
}

export interface PreferenceState {
  foodTags: FoodTag[]
  activityTags: ActivityTag[]
  priorities: Priority[]
}

export interface FoodTag {
  id: string
  label: string
  emoji: string
  selected: boolean
  recommended: boolean
}

export interface ActivityTag {
  id: string
  label: string
  emoji: string
  selected: boolean
  recommended: boolean
}

export interface Priority {
  id: string
  label: string
  emoji: string
  order: number
}

/** App view states */
export type AppState =
  | 'idle'
  | 'streaming'
  | 'plans_displayed'
  | 'hil_editing'
  | 'preferences'
  | 'confirmed'
