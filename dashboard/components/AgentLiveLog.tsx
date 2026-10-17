'use client'

import { useEffect, useMemo, useRef } from 'react'
import Box from '@mui/material/Box'
import ButtonBase from '@mui/material/ButtonBase'
import { keyframes } from '@mui/material/styles'
import AgentStreamLine, { LOG_COLORS } from '@/components/AgentStreamLine'
import { buildAgentLogViewModel, type AgentTaskEvent } from '@/lib/agentStream'

interface Props {
  title: string
  lines: string[]
  running: boolean
  /** Premier état reçu du serveur (sinon « Connexion au flux... »). */
  loaded: boolean
  open: boolean
  onOpenChange: (open: boolean) => void
}

const blink = keyframes`50% { opacity: 0; }`
// Distance au bas (px) sous laquelle on considère que l'utilisateur suit le flux.
const STICK_THRESHOLD_PX = 24

function formatTask(task: AgentTaskEvent | null): string {
  if (!task) return ''
  const parts: string[] = []
  if (task.tool_uses != null) parts.push(`${task.tool_uses} outil${task.tool_uses > 1 ? 's' : ''}`)
  if (task.tokens != null) parts.push(`${task.tokens.toLocaleString('fr-FR')} tokens`)
  if (task.duration_ms != null) {
    const s = Math.round(task.duration_ms / 1000)
    parts.push(s >= 60 ? `${Math.floor(s / 60)} min ${s % 60} s` : `${s} s`)
  }
  return parts.join(' · ')
}

/** Terminal d'exécution d'un sous-agent : en-tête repliable, badge live, défilement qui suit le flux. */
export default function AgentLiveLog({ title, lines, running, loaded, open, onOpenChange }: Props) {
  const { items, task } = useMemo(() => buildAgentLogViewModel(lines, running), [lines, running])
  const scrollRef = useRef<HTMLDivElement>(null)
  const stickToBottom = useRef(true)

  useEffect(() => {
    const el = scrollRef.current
    if (open && el && stickToBottom.current) el.scrollTop = el.scrollHeight
  }, [items, open])

  const meta = formatTask(task)
  return (
    <Box sx={{ mt: 2, borderRadius: 1, overflow: 'hidden', bgcolor: LOG_COLORS.background }}>
      <ButtonBase
        onClick={() => onOpenChange(!open)}
        data-open={open}
        sx={{
          width: '100%',
          justifyContent: 'flex-start',
          gap: 1,
          px: 1.5,
          py: 1,
          color: LOG_COLORS.assistant,
          fontFamily: 'monospace',
          fontSize: '0.8rem',
          textAlign: 'left',
        }}
      >
        <Box
          component="span"
          sx={{ display: 'inline-block', transition: 'transform 0.15s', transform: open ? 'rotate(90deg)' : 'none' }}
        >
          ▶
        </Box>
        <span>{title}</span>
        {!open && !running && (
          <Box component="span" sx={{ color: LOG_COLORS.meta }}>
            — afficher la trace
          </Box>
        )}
        {running && (
          <Box
            component="span"
            sx={{ px: 0.75, borderRadius: 0.5, bgcolor: '#14532d', color: '#4ade80', fontSize: '0.7rem', fontWeight: 700 }}
          >
            live
          </Box>
        )}
        {meta && (
          <Box component="span" sx={{ ml: 'auto', color: LOG_COLORS.meta }}>
            {task?.description && running ? `${task.description} · ` : ''}
            {meta}
          </Box>
        )}
      </ButtonBase>

      {open && (
        <Box
          ref={scrollRef}
          onScroll={(e) => {
            const el = e.currentTarget
            stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < STICK_THRESHOLD_PX
          }}
          sx={{
            maxHeight: 800,
            overflowY: 'auto',
            px: 1.5,
            pb: 1.5,
            fontFamily: 'monospace',
            fontSize: '0.78rem',
            lineHeight: 1.5,
            whiteSpace: 'pre-wrap',
            overflowWrap: 'anywhere',
            color: LOG_COLORS.raw,
          }}
        >
          {lines.length === 0 && (
            <Box sx={{ color: LOG_COLORS.meta }}>
              {running || !loaded ? 'Connexion au flux...' : 'Aucune trace enregistrée pour cette étape.'}
            </Box>
          )}
          {items.map((item) => (
            <AgentStreamLine key={`${item.id}-${item.phase}`} item={item} />
          ))}
          {running && (
            <Box component="span" sx={{ color: LOG_COLORS.assistant, animation: `${blink} 1s step-end infinite` }}>
              |
            </Box>
          )}
        </Box>
      )}
    </Box>
  )
}
