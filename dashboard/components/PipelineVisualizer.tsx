'use client'

import useSWR from 'swr'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import Chip from '@mui/material/Chip'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import CircularProgress from '@mui/material/CircularProgress'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import ErrorIcon from '@mui/icons-material/Error'
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty'
import PendingIcon from '@mui/icons-material/Pending'
import ArrowForwardIcon from '@mui/icons-material/ArrowForward'
import { fetcher } from '@/lib/api'

const AGENTS_LONG = [
  { key: 'scenario_agent', label: 'Scénariste' },
  { key: 'media_agent', label: 'Chercheur Média' },
  { key: 'narrator_agent', label: 'Narrateur Voix' },
  { key: 'editor_agent', label: 'Monteur Vidéo' },
  { key: 'subtitle_agent', label: 'Sous-titreur' },
  { key: 'critic_agent', label: 'Critique IA' },
  { key: 'clipper_agent', label: 'Découpeur Shorts' },
  { key: 'short_editor_agent', label: 'Éditeur Shorts' },
]

const AGENTS_SHORT = [
  { key: 'scenario_agent', label: 'Scénariste' },
  { key: 'media_agent', label: 'Chercheur Média' },
  { key: 'narrator_agent', label: 'Narrateur Voix' },
  { key: 'editor_agent', label: 'Monteur Vidéo' },
  { key: 'subtitle_agent', label: 'Sous-titreur' },
  { key: 'critic_agent', label: 'Critique IA' },
  { key: 'short_editor_agent', label: 'Éditeur Shorts' },
]

function StatusIcon({ status }: { status: string }) {
  if (status === 'success') return <CheckCircleIcon color="success" fontSize="small" />
  if (status === 'failed') return <ErrorIcon color="error" fontSize="small" />
  if (status === 'running') return <CircularProgress size={16} />
  return <PendingIcon color="disabled" fontSize="small" />
}

interface Props {
  projectId: string
  isShort?: boolean
}

export default function PipelineVisualizer({ projectId, isShort = false }: Props) {
  const { data: statuses } = useSWR<Record<string, string>>(
    `/api/v1/agents/status/${projectId}`,
    fetcher,
    { refreshInterval: 2000 },
  )

  const agents = isShort ? AGENTS_SHORT : AGENTS_LONG

  return (
    <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, alignItems: 'center' }}>
      {agents.map((agent, idx) => {
        const status = statuses?.[agent.key] ?? 'pending'
        return (
          <Box key={agent.key} sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Card
              sx={{
                minWidth: 130,
                border: status === 'running' ? '1px solid #7C3AED' : undefined,
              }}
            >
              <CardContent sx={{ py: 1.5, px: 2, '&:last-child': { pb: 1.5 } }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <StatusIcon status={status} />
                  <Box>
                    <Typography variant="caption" color="text.secondary">
                      Agent {idx + 1}
                    </Typography>
                    <Typography variant="body2" fontWeight={600} noWrap>
                      {agent.label}
                    </Typography>
                  </Box>
                </Box>
              </CardContent>
            </Card>
            {idx < agents.length - 1 && (
              <ArrowForwardIcon sx={{ color: 'text.disabled', fontSize: 18 }} />
            )}
          </Box>
        )
      })}
    </Box>
  )
}
