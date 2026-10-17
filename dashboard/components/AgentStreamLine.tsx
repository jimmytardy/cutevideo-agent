'use client'

import Box from '@mui/material/Box'
import type { AgentLogItem, AgentToolEvent } from '@/lib/agentStream'

export const LOG_COLORS = {
  background: '#0b1220',
  raw: '#cbd5e1',
  thinking: '#94a3b8',
  assistant: '#e2e8f0',
  tool: '#7dd3fc',
  running: '#fbbf24',
  meta: '#64748b',
  error: '#f87171',
}

const MAX_BODY_CHARS = 800
const PREVIEW_CHARS = 80

const detailsSx = {
  '& > summary': { cursor: 'pointer', listStyle: 'none', userSelect: 'none' },
  '& > summary::-webkit-details-marker': { display: 'none' },
  '& > summary::before': { content: '"▸ "', color: LOG_COLORS.meta },
  '&[open] > summary::before': { content: '"▾ "' },
}

function clip(text: string, limit: number): string {
  return text.length <= limit ? text : `${text.slice(0, limit)}…`
}

function oneLine(text: string, limit = PREVIEW_CHARS): string {
  return clip(text.replace(/\s+/g, ' ').trim(), limit)
}

function formatValue(value: unknown): string {
  if (typeof value === 'string') return clip(value, MAX_BODY_CHARS)
  return clip(JSON.stringify(value, null, 2), MAX_BODY_CHARS)
}

/** Argument le plus parlant d'un appel d'outil (commande, fichier, motif). */
function toolPreview(event: AgentToolEvent): string {
  const args = event.args
  if (!args || typeof args !== 'object') return ''
  const a = args as Record<string, unknown>
  const value = a.command ?? a.file_path ?? a.pattern ?? a.path ?? a.description
  return typeof value === 'string' ? oneLine(value, 90) : ''
}

function TextBlock({ item }: { item: Extract<AgentLogItem, { kind: 'text' }> }) {
  const color = item.role === 'thinking' ? LOG_COLORS.thinking : LOG_COLORS.assistant
  const fontStyle = item.role === 'thinking' ? 'italic' : 'normal'
  if (item.phase === 'live') {
    return (
      <Box sx={{ color, fontStyle }}>
        <Box component="span" sx={{ color: LOG_COLORS.meta }}>
          {item.role}{' '}
        </Box>
        {item.text}
      </Box>
    )
  }
  return (
    <Box component="details" sx={{ ...detailsSx, color, fontStyle }}>
      <summary>
        {item.role} (done) <Box component="span" sx={{ color: LOG_COLORS.meta }}>— {oneLine(item.text)}</Box>
      </summary>
      <Box sx={{ pl: 2 }}>{item.text}</Box>
    </Box>
  )
}

function ToolBlock({ item }: { item: Extract<AgentLogItem, { kind: 'tool' }> }) {
  const { event } = item
  const status = event.status ?? 'running'
  const color = status === 'error' ? LOG_COLORS.error : status === 'running' ? LOG_COLORS.running : LOG_COLORS.tool
  const preview = toolPreview(event)
  return (
    <Box component="details" data-status={status} open={item.phase === 'live' && status === 'running'} sx={detailsSx}>
      <Box component="summary" sx={{ color }}>
        tool {event.name || '?'} — {status}
        {preview && (
          <Box component="span" sx={{ color: LOG_COLORS.meta }}>
            {' '}· {preview}
          </Box>
        )}
      </Box>
      <Box sx={{ pl: 2, color: LOG_COLORS.raw }}>
        {event.args !== undefined && (
          <>
            <Box sx={{ color: LOG_COLORS.meta }}>args</Box>
            <Box>{formatValue(event.args)}</Box>
          </>
        )}
        {event.result !== undefined && (
          <>
            <Box sx={{ color: LOG_COLORS.meta, mt: 0.5 }}>result</Box>
            <Box sx={{ color: status === 'error' ? LOG_COLORS.error : undefined }}>{formatValue(event.result)}</Box>
          </>
        )}
      </Box>
    </Box>
  )
}

/** Une ligne du terminal ; la `key` doit inclure la phase pour replier un bloc quand il n'est plus live. */
export default function AgentStreamLine({ item }: { item: AgentLogItem }) {
  switch (item.kind) {
    case 'text':
      return <TextBlock item={item} />
    case 'tool':
      return <ToolBlock item={item} />
    case 'error':
      return <Box sx={{ color: LOG_COLORS.error }}>Erreur agent : {item.text}</Box>
    case 'raw':
      return <Box sx={{ color: item.text.startsWith('---') ? LOG_COLORS.meta : LOG_COLORS.raw }}>{item.text}</Box>
  }
}
