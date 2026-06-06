import type { ProfileOverride, SSEEvent } from './types'

async function* readSSE(res: Response): AsyncGenerator<SSEEvent> {
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`${res.status} ${text}`)
  }

  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const parts = buffer.split('\n\n')
    buffer = parts.pop() ?? ''
    for (const block of parts) {
      const line = block.trim()
      if (!line.startsWith('data: ')) continue
      try {
        yield JSON.parse(line.slice(6)) as SSEEvent
      } catch {
        // skip parse errors
      }
    }
  }
}

export async function* streamAgent(
  userInput: string,
  forceFailure?: string | null,
  overrides: ProfileOverride[] = [],
): AsyncGenerator<SSEEvent> {
  const res = await fetch('/v1/agent/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      user_input: userInput,
      overrides,
      ...(forceFailure ? { force_failure: forceFailure } : {}),
    }),
  })
  yield* readSSE(res)
}

export async function* replanAgent(
  sessionId: string,
  overrides: ProfileOverride[],
  note?: string,
): AsyncGenerator<SSEEvent> {
  const res = await fetch('/v1/agent/replan', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId,
      overrides,
      ...(note ? { note } : {}),
    }),
  })
  yield* readSSE(res)
}

export interface ConfirmResult {
  status: string
  session_id: string
  plan_id: string
  executed: number
  failed: number
  orders: Array<{ stage: string; order_id: string; status: string }>
  summary_card?: { title?: string; share_text?: string; body_markdown?: string }
  trace?: string[]
  trace_tail?: string[]
}

export async function confirmAgent(
  sessionId: string,
  planId: string,
  selectedAddonIds: string[] = [],
): Promise<ConfirmResult> {
  const res = await fetch('/v1/agent/confirm', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId,
      plan_id: planId,
      selected_addon_ids: selectedAddonIds,
    }),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`${res.status} ${text}`)
  }
  return res.json() as Promise<ConfirmResult>
}
