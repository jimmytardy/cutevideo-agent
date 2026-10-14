'use client'

import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Chip from '@mui/material/Chip'
import MenuItem from '@mui/material/MenuItem'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'

import type { ChannelCostEstimate } from '@/lib/api'
import type { ChannelSettingsForm, UpdateChannelForm } from '@/lib/channelSettingsForm'
import { AI_PLANS, FALLBACK_OPTIONS } from '@/lib/channelSettingsOptions'

interface Props {
  form: ChannelSettingsForm
  update: UpdateChannelForm
  costEstimate: ChannelCostEstimate | null
}

const planLabel = (value: string) => AI_PLANS.find((p) => p.value === value)?.label || value

export default function AiMediaTab({ form, update, costEstimate }: Props) {
  const selectedPlan = AI_PLANS.find((p) => p.value === form.ai_plan)

  return (
    <>
      <Typography variant="h6" sx={{ mb: 1 }}>Générateur d&apos;images IA</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Flux (fal.ai) et Google Imagen 3 — utilisés quand les banques d&apos;images libres ne suffisent pas.
        « Désactivé » interdit aussi les images IA dans Claude Studio.
      </Typography>

      <TextField select fullWidth label="Plan images IA" value={form.ai_plan} sx={{ mb: 2 }}
        onChange={(e) => {
          const plan = e.target.value
          update({ ai_plan: plan, ai_fallback_chain: (FALLBACK_OPTIONS[plan] || [])[0] || '' })
        }}>
        {AI_PLANS.map((p) => <MenuItem key={p.value} value={p.value}>{p.label}</MenuItem>)}
      </TextField>

      {selectedPlan?.family && <Chip label={selectedPlan.family} size="small" sx={{ mb: 2 }} />}

      {form.ai_plan !== 'off' && (
        <>
          <TextField select fullWidth label="Fallback si échec" value={form.ai_fallback_chain} sx={{ mb: 2 }}
            onChange={(e) => update({ ai_fallback_chain: e.target.value })}>
            <MenuItem value="">Aucun</MenuItem>
            {(FALLBACK_OPTIONS[form.ai_plan] || []).map((p) => (
              <MenuItem key={p} value={p}>{planLabel(p)}</MenuItem>
            ))}
          </TextField>

          <Box sx={{ display: 'flex', gap: 2, mb: 2, flexWrap: 'wrap' }}>
            <TextField type="number" label="Max img/segment" value={form.max_images_per_segment}
              onChange={(e) => update({ max_images_per_segment: e.target.value })} />
            <TextField type="number" label="Max img/vidéo" value={form.max_ai_images_per_video}
              onChange={(e) => update({ max_ai_images_per_video: e.target.value })} />
            <TextField type="number" label="Max img/semaine (opt.)" value={form.max_ai_images_per_week}
              onChange={(e) => update({ max_ai_images_per_week: e.target.value })} />
            <TextField type="number" label="Taux fallback % (opt.)" value={form.fallback_rate_override}
              inputProps={{ min: 0, max: 100, step: 1 }}
              helperText="Override niche — laisser vide pour auto"
              onChange={(e) => update({ fallback_rate_override: e.target.value })} />
          </Box>
        </>
      )}

      {costEstimate && (
        <Alert severity="info" sx={{ mb: 3 }}>
          <Typography variant="subtitle2">
            ~{costEstimate.ai_images.images_per_week} images IA / semaine
            · ~{costEstimate.ai_images.cost_eur_per_week.toFixed(2)} € / sem
            · ~{costEstimate.ai_images.cost_eur_per_month.toFixed(2)} € / mois
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Niche {costEstimate.ai_images.breakdown.theme_category} · taux{' '}
            {(costEstimate.ai_images.breakdown.fallback_rate * 100).toFixed(0)} % ·{' '}
            {costEstimate.ai_images.breakdown.videos_per_week} vidéos/sem · plan{' '}
            {costEstimate.ai_images.plan_label}
          </Typography>
        </Alert>
      )}
    </>
  )
}
