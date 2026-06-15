'use client'

import useSWR from 'swr'
import Stack from '@mui/material/Stack'
import Alert from '@mui/material/Alert'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import CriticReportDetail from './CriticReportDetail'
import { fetcher, type CriticReport } from '@/lib/api'

interface Props {
  projectId: string
}

export default function CriticFeedback({ projectId }: Props) {
  const { data: reports } = useSWR<CriticReport[]>(
    `/api/v1/projects/${projectId}/critic-reports`,
    fetcher,
    { refreshInterval: 5000 },
  )

  if (!reports || reports.length === 0) {
    return (
      <Alert severity="info">
        Aucun rapport de critique disponible — lancez le pipeline d&apos;abord.
      </Alert>
    )
  }

  return (
    <Stack spacing={2}>
      {reports.map((report, idx) => {
        const isLast = idx === reports.length - 1
        return (
          <Card key={report.id} variant={isLast ? 'elevation' : 'outlined'} elevation={isLast ? 3 : 0}>
            <CardContent>
              <CriticReportDetail
                report={report}
                iterationLabel={report.iteration ?? idx + 1}
                showLastBadge={isLast}
              />
            </CardContent>
          </Card>
        )
      })}
    </Stack>
  )
}
