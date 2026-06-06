/** SSE event from the backend streaming endpoint */
export interface SSEEvent {
  event: 'start' | 'state' | 'final' | 'done' | 'error'
  user_input?: string
  force_failure?: string | null
  state?: AgentStatePayload
  summary?: SummaryPayload
  summary_card?: SummaryCard
  /** Included in final event as fallback in case state events are dropped */
  plan?: PlanData
  plan_alternatives?: PlanData[]
  message?: string
}

export interface AgentStatePayload {
  user_input?: string
  trace?: string[]
  group_profile?: Record<string, unknown>
  plan?: PlanData
  plan_alternatives?: PlanData[]
  plan_iteration?: number
  executed_calls?: unknown[]
  failed_calls?: unknown[]
}

// ── Real backend Plan model (matches backend/schemas.py Plan) ──

export interface PlanData {
  summary: string
  stages: PlanStageData[]
  total_duration_hours: number
  total_cost_estimate: number
  score: number
  order_label: string
  version: number
  locked_stages: string[]
}

export interface PlanStageData {
  name: string // "玩" / "吃" / "加餐" / "通勤"
  start_time: string
  end_time: string
  primary: POICandidateData
  backups: POICandidateData[]
  notes: string
}

export interface POICandidateData {
  poi_id: string
  name: string
  category: string
  score: number
  reason: string
  metadata: Record<string, unknown>
}

// ── Revision types (matches backend/schemas.py) ──

export interface PlanPatch {
  target: 'play' | 'food' | 'addon' | 'route'
  action: 'replace' | 'insert' | 'remove' | 'reorder' | 'lock'
  constraints: string[]
  category?: string | null
}

export interface PlanEvent {
  event_type:
    | 'plan_created'
    | 'stage_replaced'
    | 'stage_inserted'
    | 'stage_removed'
    | 'stages_reordered'
    | 'stage_locked'
  summary: string
  timestamp: string
  version: number
}

export interface RevisePlanRequest {
  plan: Record<string, unknown>
  profile: Record<string, unknown>
  feedback: string
  revision_round: number
  revision_history: Record<string, unknown>[]
  locked_stages: string[]
}

export interface RevisePlanResponse {
  updated_plan: Record<string, unknown>
  status: 'applied' | 'rejected'
  revision_round: number
  plan_snapshots: Record<string, unknown>[]
  plan_events: PlanEvent[]
  patches_applied: number
  locked_stages: string[]
  /** Regenerated alternative plans (different POIs from revised plan) */
  alternative_plans: Record<string, unknown>[]
}

// ── Summary ──

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

// ── Frontend display models ──

export interface ChatMessage {
  id: string
  role: 'ai' | 'user'
  type: 'text' | 'progress' | 'plans' | 'preferences' | 'welcome'
  text?: string
  plans?: DisplayPlan[]
  progressSteps?: ProgressStep[]
  preferences?: PreferenceState
  planEvents?: PlanEvent[]
  timestamp: number
}

export interface DisplayPlan {
  id: string
  title: string
  play: DisplayStage
  eat: DisplayStage
  addon?: DisplayStage
  /** Computed transit segments between stages */
  transits: DisplayTransit[]
  totalPrice: string
  score: number
  highlights: string[]
  lockedStages: string[]
  version: number
  /** Raw backend plan — kept for revision API calls */
  rawPlan: Record<string, unknown>
}

export interface DisplayStage {
  name: string
  time: string
  startTime: string
  endTime: string
  desc: string
  tags: string[]
  /** POI metadata: distance_km, avg_price, open_hours, etc. */
  meta?: Record<string, unknown>
}

export interface DisplayTransit {
  from: string
  to: string
  startTime: string
  endTime: string
  durationMin: number
  distanceKm?: number
  mode: string
  note?: string
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
  | 'preferences'
  | 'confirmed'
