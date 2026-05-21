'use client'

import useSWR from 'swr'
import Box from '@mui/material/Box'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Typography from '@mui/material/Typography'
import LinearProgress from '@mui/material/LinearProgress'
import Chip from '@mui/material/Chip'
import Alert from '@mui/material/Alert'
import { BarChart } from '@mui/x-charts/BarChart'
import { fetcher } from '@/lib/api'

interface CriticReport {
  id: string
  iteration: number
  decision: string
  global_score: number
  feedback: {
    rhythm?: number
    educational_value?: number
    visual_quality?: number
    structure?: number
    comments?: string
  }
  requested_changes: Array<{ agent: string; change_description: string }>
}

interface Props {
  projectId: string
}

export default function CriticFeedback({ projectId }: Props) {
  const { data: runs } = useSWR(
    `/api/v1/agents/runs/${projectId}`,
    fetcher,
    { refreshInterval: 3000 },
  )

  const criticRuns = runs?.filter((r: { agent_name: string }) => r.agent_name === 'critic_agent') ?? []
  const latest = criticRuns[0]

  if (!latest?.output_json) {
    return (
      <Alert severity="info">
        Aucun rapport de critique disponible — lancez le pipeline d&apos;abord.
      </Alert>
    )
  }

  const score = latest.output_json.score as number ?? 0
  const decision = latest.output_json.decision as string ?? 'pending'

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <Card>
        <CardContent>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2 }}>
            <Typography variant="h6">Score global</Typography>
            <Chip
              label={decision === 'approve' ? 'Approuvé' : 'À améliorer'}
              color={decision === 'approve' ? 'success' : 'warning'}
            />
          </Box>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <LinearProgress
              variant="determinate"
              value={score}
              sx={{ flex: 1, height: 12, borderRadius: 6 }}
              color={score >= 70 ? 'success' : score >= 50 ? 'warning' : 'error'}
            />
            <Typography variant="h5" fontWeight={700}>
              {score}/100
            </Typography>
          </Box>
        </CardContent>
      </Card>
    </Box>
  )
}
