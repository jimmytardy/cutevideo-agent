'use client'

import useSWR from 'swr'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import Paper from '@mui/material/Paper'
import Chip from '@mui/material/Chip'
import Button from '@mui/material/Button'
import Alert from '@mui/material/Alert'
import Stack from '@mui/material/Stack'
import CircularProgress from '@mui/material/CircularProgress'
import DownloadIcon from '@mui/icons-material/Download'
import { authenticatedMediaUrl, fetcher, type FinalPreview } from '@/lib/api'

const VIDEO_TYPE_LABELS: Record<string, string> = {
  long: 'Vidéo longue',
  short_master: 'Short master',
  short_youtube: 'Short YouTube',
  short_tiktok: 'Short TikTok',
  short_instagram: 'Short Instagram',
}

interface Props {
  projectId: string
  refreshInterval?: number
}

export default function FinalPreviewSection({ projectId, refreshInterval = 5000 }: Props) {
  const { data, isLoading, error } = useSWR<FinalPreview>(
    `/api/v1/projects/${projectId}/final-preview`,
    fetcher,
    { refreshInterval },
  )

  if (isLoading && !data) {
    return (
      <Paper variant="outlined" sx={{ p: 2, mb: 3, borderRadius: 2 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
          <CircularProgress size={18} />
          <Typography variant="body2" color="text.secondary">
            Chargement de l&apos;aperçu…
          </Typography>
        </Box>
      </Paper>
    )
  }

  if (error) {
    return (
      <Alert severity="warning" sx={{ mb: 3 }}>
        Impossible de charger l&apos;aperçu final.
      </Alert>
    )
  }

  if (!data?.video) {
    return (
      <Paper variant="outlined" sx={{ p: 2, mb: 3, borderRadius: 2 }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 0.5 }}>
          Aperçu final
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Aucune vidéo disponible pour le moment. Lancez ou poursuivez le pipeline pour générer le montage.
        </Typography>
      </Paper>
    )
  }

  const { video } = data
  const typeLabel = VIDEO_TYPE_LABELS[video.video_type ?? ''] ?? (video.video_type ?? 'Vidéo')

  return (
    <Paper variant="outlined" sx={{ p: 2, mb: 3, borderRadius: 2 }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1.5 }}>
        Aperçu final
      </Typography>

      <Box
        component="video"
        controls
        sx={{ width: '100%', borderRadius: 1, maxHeight: 480, bgcolor: 'black', display: 'block' }}
        src={data.stream_url ? authenticatedMediaUrl(data.stream_url) : undefined}
      />

      <Stack direction="row" spacing={1} sx={{ mt: 1.5, flexWrap: 'wrap', gap: 1 }} alignItems="center">
        <Chip size="small" label={typeLabel} color="primary" />
        <Chip
          size="small"
          label={video.status}
          color={video.status === 'approved' ? 'success' : 'default'}
          variant="outlined"
        />
        {video.duration_s != null && (
          <Chip size="small" label={`${Math.round(video.duration_s)} s`} variant="outlined" />
        )}
        {video.iteration > 0 && (
          <Chip size="small" label={`Itération ${video.iteration}`} variant="outlined" />
        )}
        {data.subtitles_available && data.subtitles_download_url && (
          <Button
            size="small"
            variant="outlined"
            startIcon={<DownloadIcon />}
            component="a"
            href={
              data.subtitles_download_url
                ? authenticatedMediaUrl(data.subtitles_download_url)
                : undefined
            }
            download
          >
            Télécharger les sous-titres (.srt)
          </Button>
        )}
      </Stack>

      {data.subtitles_note && (
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
          {data.subtitles_note}
        </Typography>
      )}

      {video.video_type === 'long' && !data.subtitles_available && (
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
          Les sous-titres .srt apparaîtront ici une fois l&apos;étape Sous-titreur terminée.
        </Typography>
      )}
    </Paper>
  )
}
