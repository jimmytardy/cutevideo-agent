'use client'

import { useEffect, useState } from 'react'
import { API_BASE, authenticatedMediaUrl, fetcher } from '@/lib/api'
import { coalesceAgentStreamLogLine } from '@/lib/agentStream'

interface LogSnapshot {
  lines: string[]
  running: boolean
}

const POLL_INTERVAL_MS = 2000
// Échecs consécutifs du polling de repli avant abandon (run supprimé, session expirée…).
const MAX_POLL_FAILURES = 5

/**
 * Trace d'un sous-agent : `history` à la connexion (remplace les lignes), puis `line` (coalescée
 * localement) et `done`. Si le flux SSE tombe (proxy qui coupe), repli sur un polling de `/log`.
 */
export function useAgentLogSse(projectId: string, runId: string, enabled: boolean) {
  const [lines, setLines] = useState<string[]>([])
  const [running, setRunning] = useState(false)
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    if (!enabled) return
    const base = `${API_BASE}/agents/runs/${projectId}/${runId}/log`
    let closed = false
    let finished = false
    let failures = 0
    let timer: ReturnType<typeof setTimeout> | undefined

    setLines([])
    setRunning(false)
    setConnected(false)

    const applySnapshot = (data: LogSnapshot) => {
      // Historique vide pendant un run : on garde les lignes déjà reçues.
      setLines((prev) => (data.lines.length > 0 || !data.running ? data.lines : prev))
      setRunning(data.running)
      setConnected(true)
    }

    const poll = async () => {
      try {
        const data = await fetcher<LogSnapshot>(base)
        if (closed) return
        failures = 0
        applySnapshot(data)
        if (data.running) timer = setTimeout(poll, POLL_INTERVAL_MS)
      } catch {
        failures += 1
        if (!closed && failures < MAX_POLL_FAILURES) timer = setTimeout(poll, POLL_INTERVAL_MS * 2)
      }
    }

    const source = new EventSource(authenticatedMediaUrl(`${base}/stream`))
    source.addEventListener('history', (e) => applySnapshot(JSON.parse((e as MessageEvent<string>).data) as LogSnapshot))
    source.addEventListener('line', (e) => {
      const { line } = JSON.parse((e as MessageEvent<string>).data) as { line: string }
      setLines((prev) => {
        const next = [...prev]
        coalesceAgentStreamLogLine(next, line)
        return next
      })
      setRunning(true)
    })
    source.addEventListener('done', () => {
      finished = true
      setRunning(false)
      source.close()
    })
    source.onerror = () => {
      source.close()
      if (!closed && !finished) void poll()
    }

    return () => {
      closed = true
      source.close()
      clearTimeout(timer)
    }
  }, [projectId, runId, enabled])

  return { lines, running, connected }
}
