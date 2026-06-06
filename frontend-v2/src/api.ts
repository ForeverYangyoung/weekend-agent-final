import type { RevisePlanRequest, RevisePlanResponse, SSEEvent } from './types'

export async function* streamAgent(
  userInput: string,
  forceFailure?: string | null,
): AsyncGenerator<SSEEvent> {
  const res = await fetch('/v1/agent/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      user_input: userInput,
      ...(forceFailure ? { force_failure: forceFailure } : {}),
    }),
  })

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
      } catch (err) {
        console.warn('SSE parse error', { linePreview: line.slice(6, 200), error: String(err) })
      }
    }
  }
}

export async function revisePlan(req: RevisePlanRequest): Promise<RevisePlanResponse> {
  const res = await fetch('/v1/plan/revise', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })

  if (!res.ok) {
    const text = await res.text()
    throw new Error(`${res.status} ${text}`)
  }

  return res.json() as Promise<RevisePlanResponse>
}
