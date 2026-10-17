/**
 * Trace d'exécution d'un sous-agent Claude Studio (terminal du détail projet).
 *
 * Protocole : une ligne = un événement, brute (`--- Démarrage … ---`) ou `@agent-stream:{json}`.
 * La coalescence suit exactement `studio/agent_stream.py` (le serveur envoie la ligne fusionnée,
 * le client doit la remplacer au lieu de l'ajouter).
 */

const AGENT_STREAM_PREFIX = '@agent-stream:'

type ToolStatus = 'running' | 'completed' | 'error'

export type AgentStreamEvent =
  | { type: 'thinking'; text: string; done?: boolean }
  | { type: 'assistant'; text: string; done?: boolean }
  | { type: 'tool_call'; callId?: string; name?: string; status?: ToolStatus; args?: unknown; result?: unknown }
  | { type: 'task'; description?: string; tokens?: number | null; tool_uses?: number | null; duration_ms?: number | null }
  | { type: 'error'; text: string }

export type AgentTaskEvent = Extract<AgentStreamEvent, { type: 'task' }>
export type AgentToolEvent = Extract<AgentStreamEvent, { type: 'tool_call' }>

/** Événement structuré, ou null pour une ligne brute (ou un JSON invalide, affiché tel quel). */
function parseAgentStreamLine(line: string): AgentStreamEvent | null {
  if (!line.startsWith(AGENT_STREAM_PREFIX)) return null
  try {
    const event = JSON.parse(line.slice(AGENT_STREAM_PREFIX.length)) as unknown
    if (event && typeof event === 'object' && !Array.isArray(event) && typeof (event as { type?: unknown }).type === 'string') {
      return event as AgentStreamEvent
    }
  } catch {
    // ligne affichée en brut
  }
  return null
}

function encode(event: AgentStreamEvent): string {
  return AGENT_STREAM_PREFIX + JSON.stringify(event)
}

/** Fragment cumulatif (remplace), déjà contenu (garde) ou delta (concatène). */
function mergeStreamText(oldText: string, newText: string): string {
  if (newText.startsWith(oldText)) return newText
  if (oldText.includes(newText)) return oldText
  return oldText + newText
}

function mergeTool(prev: AgentToolEvent, next: AgentToolEvent): AgentToolEvent {
  const defined = Object.fromEntries(Object.entries(next).filter(([, v]) => v !== undefined && v !== null))
  const merged = { ...prev, ...defined } as AgentToolEvent
  if ('args' in prev) merged.args = prev.args
  return merged
}

/** Ajoute `line` à `buf` ou fusionne avec une ligne existante (modifie `buf` en place) ; renvoie la ligne résultante. */
export function coalesceAgentStreamLogLine(buf: string[], line: string): string {
  const event = parseAgentStreamLine(line)
  if (!event) {
    buf.push(line)
    return line
  }

  if ((event.type === 'thinking' || event.type === 'assistant') && buf.length > 0) {
    const prev = parseAgentStreamLine(buf[buf.length - 1])
    if (prev && prev.type === event.type && !prev.done) {
      const merged = encode({ ...prev, ...event, text: mergeStreamText(prev.text ?? '', event.text ?? '') })
      buf[buf.length - 1] = merged
      return merged
    }
  }

  if (event.type === 'task') {
    for (let i = buf.length - 1; i >= 0; i--) {
      if (parseAgentStreamLine(buf[i])?.type === 'task') {
        buf[i] = line
        return line
      }
    }
  }

  if (event.type === 'tool_call') {
    for (let i = buf.length - 1; i >= 0; i--) {
      const prev = parseAgentStreamLine(buf[i])
      if (!prev || prev.type !== 'tool_call') continue
      const same = event.callId
        ? prev.callId === event.callId
        : !prev.callId && prev.status === 'running' && prev.name === event.name
      if (same) {
        const merged = encode(mergeTool(prev, event))
        buf[i] = merged
        return merged
      }
    }
  }

  buf.push(line)
  return line
}

export type LogPhase = 'live' | 'closed'

export type AgentLogItem =
  | { kind: 'text'; id: string; role: 'thinking' | 'assistant'; text: string; done: boolean; phase: LogPhase }
  | { kind: 'tool'; id: string; event: AgentToolEvent; phase: LogPhase }
  | { kind: 'error'; id: string; text: string; phase: LogPhase }
  | { kind: 'raw'; id: string; text: string; phase: LogPhase }

interface AgentLogViewModel {
  items: AgentLogItem[]
  /** Dernière progression (tokens, outils, durée) : affichée dans l'en-tête, pas dans la liste. */
  task: AgentTaskEvent | null
}

/** Lignes → blocs à ids stables ; seul le dernier bloc est `live`, et seulement pendant le run. */
export function buildAgentLogViewModel(lines: string[], running: boolean): AgentLogViewModel {
  const items: AgentLogItem[] = []
  const toolIndex = new Map<string, number>()
  const counters = { thinking: 0, assistant: 0 }
  let task: AgentTaskEvent | null = null

  lines.forEach((line, i) => {
    const event = parseAgentStreamLine(line)
    if (!event) {
      items.push({ kind: 'raw', id: `raw-${i}`, text: line, phase: 'closed' })
      return
    }
    switch (event.type) {
      case 'thinking':
      case 'assistant':
        items.push({
          kind: 'text',
          id: `${event.type}-${counters[event.type]++}`,
          role: event.type,
          text: event.text ?? '',
          done: !!event.done,
          phase: 'closed',
        })
        return
      case 'tool_call': {
        const key = event.callId ? `tool-${event.callId}` : `tool-${i}`
        const existing = toolIndex.get(key)
        if (existing !== undefined) {
          const prev = items[existing] as Extract<AgentLogItem, { kind: 'tool' }>
          items[existing] = { ...prev, event: mergeTool(prev.event, event) }
        } else {
          toolIndex.set(key, items.length)
          items.push({ kind: 'tool', id: key, event, phase: 'closed' })
        }
        return
      }
      case 'task':
        task = event
        return
      case 'error':
        items.push({ kind: 'error', id: `error-${i}`, text: event.text ?? '', phase: 'closed' })
        return
    }
  })

  const last = items[items.length - 1]
  // Une réflexion terminée reste repliée ; sinon le dernier bloc est « live » pendant le run.
  if (running && last && !(last.kind === 'text' && last.role === 'thinking' && last.done)) {
    items[items.length - 1] = { ...last, phase: 'live' }
  }
  return { items, task }
}
