'use client'

import { useState } from 'react'
import useSWR from 'swr'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import CardActionArea from '@mui/material/CardActionArea'
import Chip from '@mui/material/Chip'
import CircularProgress from '@mui/material/CircularProgress'
import Alert from '@mui/material/Alert'
import Dialog from '@mui/material/Dialog'
import DialogTitle from '@mui/material/DialogTitle'
import DialogContent from '@mui/material/DialogContent'
import DialogActions from '@mui/material/DialogActions'
import Button from '@mui/material/Button'
import Divider from '@mui/material/Divider'
import List from '@mui/material/List'
import ListItem from '@mui/material/ListItem'
import ListItemText from '@mui/material/ListItemText'
import Accordion from '@mui/material/Accordion'
import AccordionSummary from '@mui/material/AccordionSummary'
import AccordionDetails from '@mui/material/AccordionDetails'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import TrendingUpIcon from '@mui/icons-material/TrendingUp'
import GroupIcon from '@mui/icons-material/Group'
import LightbulbIcon from '@mui/icons-material/Lightbulb'
import AppShell from '@/components/AppShell'
import { listMarketAnalyses, getMarketAnalysis, type MarketAnalysisListItem, type MarketAnalysisDetail } from '@/lib/api'

const VERDICT_COLOR: Record<string, 'success' | 'warning' | 'error'> = {
  favorable: 'success',
  nuanced: 'warning',
  crowded: 'error',
}

const VERDICT_LABEL: Record<string, string> = {
  favorable: 'Favorable',
  nuanced: 'Nuancé',
  crowded: 'Saturé',
}

function VerdictChip({ verdict }: { verdict: string | null }) {
  if (!verdict) return null
  const color = VERDICT_COLOR[verdict] ?? 'default'
  const label = VERDICT_LABEL[verdict] ?? verdict
  return <Chip label={label} size="small" color={color} />
}

function AnalysisCard({ item, onClick }: { item: MarketAnalysisListItem; onClick: () => void }) {
  const date = new Date(item.created_at).toLocaleDateString('fr-FR', {
    day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })

  return (
    <Card>
      <CardActionArea onClick={onClick}>
        <CardContent>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 1 }}>
            <Typography variant="subtitle1" fontWeight={600} sx={{ flex: 1, pr: 1 }}>
              {item.prompt}
            </Typography>
            <VerdictChip verdict={item.saturation_verdict} />
          </Box>
          {item.market_summary && (
            <Typography variant="body2" color="text.secondary" sx={{
              display: '-webkit-box',
              WebkitLineClamp: 3,
              WebkitBoxOrient: 'vertical',
              overflow: 'hidden',
              mb: 1,
            }}>
              {item.market_summary}
            </Typography>
          )}
          <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mt: 1 }}>
            {item.platforms_analyzed?.map((p) => (
              <Chip key={p} label={p} size="small" variant="outlined" />
            ))}
            <Typography variant="caption" color="text.disabled" sx={{ ml: 'auto', alignSelf: 'center' }}>
              {date}
            </Typography>
          </Box>
        </CardContent>
      </CardActionArea>
    </Card>
  )
}

function DetailDialog({ id, onClose }: { id: string; onClose: () => void }) {
  const { data, isLoading, error } = useSWR<MarketAnalysisDetail>(
    `/api/v1/markets/${id}`,
    () => getMarketAnalysis(id),
  )

  const report = data?.report

  return (
    <Dialog open onClose={onClose} maxWidth="md" fullWidth scroll="paper">
      <DialogTitle sx={{ pb: 1 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Typography variant="h6" sx={{ flex: 1 }}>{data?.prompt ?? '…'}</Typography>
          {data?.saturation_verdict && <VerdictChip verdict={data.saturation_verdict} />}
        </Box>
        {data && (
          <Typography variant="caption" color="text.secondary">
            {new Date(data.created_at).toLocaleDateString('fr-FR', {
              day: '2-digit', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit',
            })}
          </Typography>
        )}
      </DialogTitle>

      <DialogContent dividers>
        {isLoading && <CircularProgress sx={{ display: 'block', mx: 'auto', my: 4 }} />}
        {error && <Alert severity="error">Impossible de charger l&apos;analyse</Alert>}

        {report && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            {/* Summary */}
            <Box>
              <Typography variant="subtitle2" color="primary" gutterBottom>Résumé marché</Typography>
              <Typography variant="body2">{report.market_summary}</Typography>
            </Box>

            {report.differentiation_verdict && (
              <Box>
                <Typography variant="subtitle2" color="primary" gutterBottom>Différenciation</Typography>
                <Typography variant="body2">{report.differentiation_verdict}</Typography>
              </Box>
            )}

            <Divider />

            {/* Competitors */}
            {report.top_competitors?.length > 0 && (
              <Accordion defaultExpanded disableGutters elevation={0} sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 1 }}>
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <GroupIcon fontSize="small" color="action" />
                    <Typography variant="subtitle2">Concurrents ({report.top_competitors.length})</Typography>
                  </Box>
                </AccordionSummary>
                <AccordionDetails sx={{ p: 0 }}>
                  {report.top_competitors.map((c, i) => (
                    <Box key={i} sx={{ px: 2, py: 1.5, borderTop: i > 0 ? '1px solid' : 'none', borderColor: 'divider' }}>
                      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
                        <Typography variant="body2" fontWeight={600}>{c.name}</Typography>
                        <Box sx={{ display: 'flex', gap: 0.5 }}>
                          <Chip label={c.platform} size="small" variant="outlined" />
                          {c.subscriber_count != null && (
                            <Chip label={`${(c.subscriber_count / 1000).toFixed(0)}k abonnés`} size="small" />
                          )}
                        </Box>
                      </Box>
                      {c.positioning && <Typography variant="caption" color="text.secondary">{c.positioning}</Typography>}
                      {c.weaknesses?.length > 0 && (
                        <Typography variant="caption" color="warning.main" sx={{ display: 'block', mt: 0.5 }}>
                          Faiblesses : {c.weaknesses.join(', ')}
                        </Typography>
                      )}
                    </Box>
                  ))}
                </AccordionDetails>
              </Accordion>
            )}

            {/* Niches */}
            {report.niche_opportunities?.length > 0 && (
              <Accordion defaultExpanded disableGutters elevation={0} sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 1 }}>
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <TrendingUpIcon fontSize="small" color="action" />
                    <Typography variant="subtitle2">Opportunités de niche ({report.niche_opportunities.length})</Typography>
                  </Box>
                </AccordionSummary>
                <AccordionDetails sx={{ p: 0 }}>
                  {report.niche_opportunities.map((n, i) => (
                    <Box key={i} sx={{ px: 2, py: 1.5, borderTop: i > 0 ? '1px solid' : 'none', borderColor: 'divider' }}>
                      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
                        <Typography variant="body2" fontWeight={600}>{n.niche_name}</Typography>
                        <Box sx={{ display: 'flex', gap: 0.5 }}>
                          <Chip label={`Score ${n.potential_score}/100`} size="small" color="success" variant="outlined" />
                          <Chip label={n.competition_level} size="small" />
                        </Box>
                      </Box>
                      <Typography variant="caption" color="text.secondary">{n.rationale}</Typography>
                      {n.differentiation_angle && (
                        <Typography variant="caption" color="primary.main" sx={{ display: 'block', mt: 0.25 }}>
                          Angle : {n.differentiation_angle}
                        </Typography>
                      )}
                    </Box>
                  ))}
                </AccordionDetails>
              </Accordion>
            )}

            {/* Recommended themes */}
            {report.recommended_themes?.length > 0 && (
              <Accordion defaultExpanded disableGutters elevation={0} sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 1 }}>
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <LightbulbIcon fontSize="small" color="action" />
                    <Typography variant="subtitle2">Thèmes recommandés ({report.recommended_themes.length})</Typography>
                  </Box>
                </AccordionSummary>
                <AccordionDetails sx={{ p: 0 }}>
                  {report.recommended_themes.map((t, i) => (
                    <Box key={i} sx={{ px: 2, py: 1.5, borderTop: i > 0 ? '1px solid' : 'none', borderColor: 'divider' }}>
                      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
                        <Typography variant="body2" fontWeight={600}>{t.name}</Typography>
                        <Chip label={`Diff. ${t.differentiation_score}/100`} size="small" color="primary" variant="outlined" />
                      </Box>
                      <Typography variant="caption" color="text.secondary">{t.content_angle}</Typography>
                      {t.why_you_can_win && (
                        <Typography variant="caption" color="success.main" sx={{ display: 'block', mt: 0.25 }}>
                          Pourquoi vous pouvez gagner : {t.why_you_can_win}
                        </Typography>
                      )}
                    </Box>
                  ))}
                </AccordionDetails>
              </Accordion>
            )}

            {/* Avoid */}
            {report.avoid?.length > 0 && (
              <Box>
                <Typography variant="subtitle2" color="error" gutterBottom>À éviter</Typography>
                <List dense disablePadding>
                  {report.avoid.map((a, i) => (
                    <ListItem key={i} sx={{ py: 0.25 }}>
                      <ListItemText primaryTypographyProps={{ variant: 'body2' }} primary={`• ${a}`} />
                    </ListItem>
                  ))}
                </List>
              </Box>
            )}

            {/* Next steps */}
            {report.next_steps?.length > 0 && (
              <Box>
                <Typography variant="subtitle2" color="primary" gutterBottom>Prochaines étapes</Typography>
                <List dense disablePadding>
                  {report.next_steps.map((s, i) => (
                    <ListItem key={i} sx={{ py: 0.25 }}>
                      <ListItemText primaryTypographyProps={{ variant: 'body2' }} primary={`${i + 1}. ${s}`} />
                    </ListItem>
                  ))}
                </List>
              </Box>
            )}
          </Box>
        )}
      </DialogContent>

      <DialogActions>
        <Button onClick={onClose}>Fermer</Button>
      </DialogActions>
    </Dialog>
  )
}

export default function MarketsPage() {
  const { data: analyses, isLoading, error } = useSWR<MarketAnalysisListItem[]>(
    '/api/v1/markets',
    listMarketAnalyses,
  )
  const [selectedId, setSelectedId] = useState<string | null>(null)

  return (
    <AppShell>
      <Box sx={{ maxWidth: 1100, mx: 'auto' }}>
        <Box sx={{ mb: 4 }}>
          <Typography variant="h5">Marchés analysés</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            Historique des analyses marché réalisées lors de l&apos;onboarding des chaînes.
          </Typography>
        </Box>

        {isLoading && <CircularProgress />}
        {error && <Alert severity="error">Impossible de charger les analyses</Alert>}
        {!isLoading && analyses?.length === 0 && (
          <Alert severity="info">
            Aucune analyse marché enregistrée. Lancez l&apos;onboarding d&apos;une chaîne pour en créer une.
          </Alert>
        )}

        <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))' }}>
          {analyses?.map((item) => (
            <AnalysisCard key={item.id} item={item} onClick={() => setSelectedId(item.id)} />
          ))}
        </Box>
      </Box>

      {selectedId && (
        <DetailDialog id={selectedId} onClose={() => setSelectedId(null)} />
      )}
    </AppShell>
  )
}
