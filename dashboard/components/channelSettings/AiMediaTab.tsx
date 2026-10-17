'use client'

import Alert from '@mui/material/Alert'
import Chip from '@mui/material/Chip'
import MenuItem from '@mui/material/MenuItem'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'

import type { ChannelCostEstimate } from '@/lib/api'
import type { ChannelSettingsForm, UpdateChannelForm } from '@/lib/channelSettingsForm'
import { AI_PLANS } from '@/lib/channelSettingsOptions'

interface Props {
  form: ChannelSettingsForm
  update: UpdateChannelForm
  costEstimate: ChannelCostEstimate | null
}

export default function AiMediaTab({ form, update, costEstimate }: Props) {
  const selectedPlan = AI_PLANS.find((p) => p.value === form.ai_plan)

  return (
    <>
      <Typography variant="h6" sx={{ mb: 1 }}>Générateur d&apos;images IA</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Flux (fal.ai) et Google Imagen 3, utilisés par Claude Studio quand ni les banques d&apos;images libres ni
        les animations ne suffisent. Le modèle choisi est celui par défaut et fixe le prix maximum : Claude peut
        prendre un modèle moins cher, si tu as la clé correspondante (fal ou compte de service GCP).
        « Désactivé » interdit les images IA.
      </Typography>

      <TextField select fullWidth label="Modèle images IA" value={form.ai_plan} sx={{ mb: 2 }}
        onChange={(e) => update({ ai_plan: e.target.value })}>
        {AI_PLANS.map((p) => <MenuItem key={p.value} value={p.value}>{p.label}</MenuItem>)}
      </TextField>

      {selectedPlan?.family && <Chip label={selectedPlan.family} size="small" sx={{ mb: 2 }} />}

      {form.ai_plan !== 'off' && (
        <TextField type="number" label="Max images IA par vidéo" value={form.max_ai_images_per_video}
          sx={{ mb: 2, display: 'block' }}
          onChange={(e) => update({ max_ai_images_per_video: e.target.value })} />
      )}

      {costEstimate && (
        <Alert severity="info" sx={{ mb: 3 }}>
          <Typography variant="subtitle2">
            Au plus ~{costEstimate.ai_images.images_per_week} images IA / semaine
            · ~{costEstimate.ai_images.cost_eur_per_week.toFixed(2)} € / sem
            · ~{costEstimate.ai_images.cost_eur_per_month.toFixed(2)} € / mois
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {costEstimate.ai_images.videos_per_week} vidéos/sem × {costEstimate.ai_images.max_ai_images_per_video}
            {' '}images max × {costEstimate.ai_images.cost_per_image_eur} € ({costEstimate.ai_images.plan_label}).
            En pratique Claude en génère beaucoup moins : il passe d&apos;abord par les banques et les animations.
          </Typography>
        </Alert>
      )}
    </>
  )
}
