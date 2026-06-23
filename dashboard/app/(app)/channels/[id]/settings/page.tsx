'use client'



import { useState, useEffect, useCallback, useMemo } from 'react'

import useSWR from 'swr'

import Box from '@mui/material/Box'

import Typography from '@mui/material/Typography'

import TextField from '@mui/material/TextField'

import Button from '@mui/material/Button'

import MenuItem from '@mui/material/MenuItem'

import FormControlLabel from '@mui/material/FormControlLabel'

import Checkbox from '@mui/material/Checkbox'

import Switch from '@mui/material/Switch'

import Alert from '@mui/material/Alert'

import CircularProgress from '@mui/material/CircularProgress'

import Chip from '@mui/material/Chip'

import Divider from '@mui/material/Divider'

import Tabs from '@mui/material/Tabs'

import Tab from '@mui/material/Tab'

import { PageContainer, PageHeader, LoadingState, useConfirmDialog } from '@/components/layout'

import { fetcher, fetchRunwayStatus, previewChannelCostEstimate, updateChannel, type Channel, type ChannelCostEstimate, type RunwayStatus } from '@/lib/api'

import {
  buildChannelUpdatePayload,
  channelSettingsFormsEqual,
  channelToFormState,
  type ChannelSettingsForm,
} from '@/lib/channelSettingsForm'

import { useUnsavedChangesWarning } from '@/lib/useUnsavedChangesWarning'



const PLATFORMS = ['youtube', 'tiktok', 'instagram']

const MODES = [

  { value: 'mixed', label: 'Mixte (long + shorts)' },

  { value: 'long_only', label: 'Longues uniquement' },

  { value: 'shorts_only', label: 'Shorts uniquement' },

]



const YOUTUBE_CATEGORIES = [

  { id: '1', label: 'Film & Animation' },

  { id: '2', label: 'Autos & Vehicles' },

  { id: '10', label: 'Music' },

  { id: '15', label: 'Pets & Animals' },

  { id: '17', label: 'Sports' },

  { id: '19', label: 'Travel & Events' },

  { id: '20', label: 'Gaming' },

  { id: '22', label: 'People & Blogs' },

  { id: '23', label: 'Comedy' },

  { id: '24', label: 'Entertainment' },

  { id: '25', label: 'News & Politics' },

  { id: '26', label: 'Howto & Style' },

  { id: '27', label: 'Education' },

  { id: '28', label: 'Science & Technology' },

  { id: '29', label: 'Nonprofits & Activism' },

]



const AI_PLANS = [

  { value: 'off', label: 'Désactivé', family: '' },

  { value: 'flux_schnell', label: 'Flux Schnell (budget)', family: 'Flux' },

  { value: 'flux_pro', label: 'Flux 1.1 Pro (standard)', family: 'Flux' },

  { value: 'flux_ultra', label: 'Flux Pro Ultra (qualité max)', family: 'Flux' },

  { value: 'imagen3_fast', label: 'Imagen 3 Fast (budget Google)', family: 'Google Imagen 3' },

  { value: 'imagen3', label: 'Imagen 3 (standard Google)', family: 'Google Imagen 3' },

]



const FALLBACK_OPTIONS: Record<string, string[]> = {

  off: [],

  flux_schnell: ['imagen3_fast', 'imagen3'],

  flux_pro: ['imagen3', 'flux_ultra'],

  flux_ultra: ['imagen3'],

  imagen3_fast: ['flux_schnell', 'flux_pro'],

  imagen3: ['flux_pro', 'flux_ultra'],

}

const TTS_ENGINES = [
  { value: 'azure', label: 'Azure Neural' },
  { value: 'gemini', label: 'Gemini Flash TTS' },
  { value: 'edge-tts', label: 'Edge TTS (gratuit)' },
]

function voiceOptionsForEngine(
  engine: string,
  azureVoices: { id: string; label: string }[] | undefined,
  geminiVoices: { id: string; label: string }[] | undefined,
) {
  if (engine === 'gemini') return geminiVoices || []
  return azureVoices || []
}



interface Props {

  params: { id: string }

}



export default function ChannelSettingsPage({ params }: Props) {

  const { id } = params

  const { data: channel, isLoading, mutate } = useSWR<Channel>(`/api/v1/channels/${id}`, fetcher)

  const { data: voices } = useSWR<{ id: string; label: string }[]>('/api/v1/config/tts/voices', fetcher)

  const { data: geminiVoices } = useSWR<{ id: string; label: string }[]>('/api/v1/config/tts/gemini-voices', fetcher)

  const { data: runwayStatus } = useSWR<RunwayStatus>(
    id ? `/api/v1/channels/${id}/runway-status` : null,
    () => fetchRunwayStatus(id),
    { refreshInterval: 30000 },
  )

  const [saving, setSaving] = useState(false)

  const [saved, setSaved] = useState(false)

  const [saveError, setSaveError] = useState<string | null>(null)

  const [form, setForm] = useState<ChannelSettingsForm | null>(null)

  const [savedForm, setSavedForm] = useState<ChannelSettingsForm | null>(null)

  const [costEstimate, setCostEstimate] = useState<ChannelCostEstimate | null>(null)

  const [tab, setTab] = useState(0)

  const { confirm, dialog: leaveConfirmDialog } = useConfirmDialog()

  const isDirty = useMemo(
    () => Boolean(form && savedForm && !channelSettingsFormsEqual(form, savedForm)),
    [form, savedForm],
  )

  useUnsavedChangesWarning(isDirty, confirm)



  const fetchCostPreview = useCallback(async (currentForm: Record<string, unknown>) => {

    try {

      const estimate = await previewChannelCostEstimate(id, {

        ai_fallback: {

          plan: currentForm.ai_plan,

          enabled: currentForm.ai_plan !== 'off',

          fallback_chain: currentForm.ai_fallback_chain ? [currentForm.ai_fallback_chain] : [],

          max_images_per_segment: Number(currentForm.max_images_per_segment),

          max_ai_images_per_video: Number(currentForm.max_ai_images_per_video),

          max_ai_images_per_week: currentForm.max_ai_images_per_week

            ? Number(currentForm.max_ai_images_per_week)

            : null,

          fallback_rate_override: currentForm.fallback_rate_override

            ? Number(currentForm.fallback_rate_override)

            : null,

        },

      })

      setCostEstimate(estimate)

    } catch {

      /* aperçu optionnel — ignorer si indisponible */

    }

  }, [id])



  useEffect(() => {

    if (!channel || form) return

    const initialForm = channelToFormState(channel)

    setForm(initialForm)

    setSavedForm(initialForm)

  }, [channel, form])



  useEffect(() => {

    if (!form) return

    const timer = setTimeout(() => fetchCostPreview(form), 300)

    return () => clearTimeout(timer)

  }, [form, fetchCostPreview])



  const handleSave = async () => {

    if (!form || !channel) return

    setSaving(true)

    setSaveError(null)

    const payload = buildChannelUpdatePayload(form, channel)

    try {

      const updated = await updateChannel(id, payload)

      await mutate(updated, { revalidate: false })

      const syncedForm = channelToFormState(updated)

      setForm(syncedForm)

      setSavedForm(syncedForm)

      setSaved(true)

      setTimeout(() => setSaved(false), 3000)

    } catch (error) {

      setSaveError(error instanceof Error ? error.message : 'Impossible d\'enregistrer — vérifiez la connexion au serveur.')

    } finally {

      setSaving(false)

    }

  }



  const selectedPlan = AI_PLANS.find((p) => p.value === form?.ai_plan)



  if (isLoading || !form) {

    return <LoadingState variant="page" />

  }



  return (

    <PageContainer maxWidth="md">

      {leaveConfirmDialog}

      <PageHeader
        title={`Paramètres — ${channel?.name ?? ''}`}
        description="Thème, format de production, plateformes, voix et générateurs IA."
        breadcrumbs={[
          { label: 'Chaînes', href: '/channels' },
          { label: channel?.name ?? 'Paramètres' },
        ]}
        actions={(
          <Button
            variant="contained"
            onClick={handleSave}
            disabled={saving}
            startIcon={saving ? <CircularProgress size={16} color="inherit" /> : undefined}
          >
            {saving ? 'Enregistrement…' : 'Enregistrer'}
          </Button>
        )}
      />

      {saved && <Alert severity="success" sx={{ mb: 2 }}>Configuration enregistrée</Alert>}

      {isDirty && !saving && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          Modifications non enregistrées — pensez à enregistrer avant de quitter la page.
        </Alert>
      )}

      {saveError && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setSaveError(null)}>{saveError}</Alert>}

      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 3, borderBottom: 1, borderColor: 'divider' }}>
        <Tab label="Général" />
        <Tab label="Voix & TTS" />
        <Tab label="IA & médias" />
      </Tabs>

      {tab === 0 && (
        <>
        <TextField fullWidth label="Catégorie / thème" value={form.theme_category} sx={{ mb: 2 }}

          onChange={(e) => setForm({ ...form, theme_category: e.target.value })}

          helperText="Valeur libre — ex: histoire, science, true_crime, cuisine… Détermine la priorité des sources média." />



        <TextField fullWidth label="Thème chaîne (theme_prompt)" multiline rows={2}

          value={form.theme_prompt} sx={{ mb: 2 }}

          onChange={(e) => setForm({ ...form, theme_prompt: e.target.value })} />



        <TextField fullWidth label="Niche (niche_prompt)" multiline rows={2}

          value={form.niche_prompt} sx={{ mb: 2 }}

          onChange={(e) => setForm({ ...form, niche_prompt: e.target.value })} />



        <TextField
          fullWidth
          label="Brief créatif"
          multiline
          rows={6}
          value={form.creative_brief}
          sx={{ mb: 2 }}
          onChange={(e) => setForm({ ...form, creative_brief: e.target.value })}
          placeholder="Décris le ton, le style narratif, les thèmes récurrents, ce qui distingue la chaîne, les interdits éditoriaux…"
          helperText="Injecté dans les prompts du scénariste, du critique et du découpeur shorts" />



        <TextField
          fullWidth
          label="Template validation média (chaîne)"
          multiline
          rows={4}
          value={form.media_validation_template as string}
          sx={{ mb: 2 }}
          onChange={(e) => setForm({ ...form, media_validation_template: e.target.value })}
          placeholder="Règles permanentes pour valider les médias (ex: toujours vérifier l'espèce exacte, rejeter les reconstitutions CGI…)"
          helperText="Fusionné dans le brief de validation de chaque vidéo" />



        <TextField
          fullWidth
          label="Seuil pertinence par défaut (chaîne)"
          type="number"
          value={form.default_min_relevance_score as string | number}
          sx={{ mb: 2 }}
          onChange={(e) => setForm({ ...form, default_min_relevance_score: e.target.value })}
          inputProps={{ min: 0, max: 100 }}
          helperText="Optionnel — remplace le seuil global (60 par défaut, 75 pour sujets précis)" />



        <TextField fullWidth label="Ton éditorial" value={form.tone} sx={{ mb: 2 }}

          onChange={(e) => setForm({ ...form, tone: e.target.value })}

          helperText="Ex: Humoristique, léger — influence scénario et voix" />



        <TextField select fullWidth label="Mode production" value={form.production_mode} sx={{ mb: 2 }}

          onChange={(e) => setForm({ ...form, production_mode: e.target.value })}>

          {MODES.map((m) => <MenuItem key={m.value} value={m.value}>{m.label}</MenuItem>)}

        </TextField>



        <Box sx={{ display: 'flex', gap: 2, mb: 2 }}>

          <TextField type="number" label="Quota longues/j" value={form.long_quota}

            onChange={(e) => setForm({ ...form, long_quota: e.target.value })} />

          <TextField type="number" label="Quota shorts/j" value={form.short_quota}

            onChange={(e) => setForm({ ...form, short_quota: e.target.value })} />

          <TextField type="number" label="Durée short cible (s)" value={form.short_duration_s}

            onChange={(e) => setForm({ ...form, short_duration_s: e.target.value })} />

          <TextField type="number" label="Durée min short (s)" helperText="Minimum TikTok : 60 s"

            value={form.min_short_duration_s}

            onChange={(e) => setForm({ ...form, min_short_duration_s: e.target.value })} />

          <TextField type="number" label="Durée max short (s)" helperText="Plafond export : 120 s (60 s max sur abonnement gratuit)"

            value={form.max_short_duration_s}

            onChange={(e) => setForm({ ...form, max_short_duration_s: e.target.value })} />

        </Box>



        <Typography variant="subtitle2" sx={{ mb: 1 }}>Plateformes actives</Typography>

        <Box sx={{ mb: 2 }}>

          {PLATFORMS.map((p) => (

            <FormControlLabel

              key={p}

              control={

                <Checkbox

                  checked={(form.enabled_platforms as string[]).includes(p)}

                  onChange={(e) => {

                    const current = form.enabled_platforms as string[]

                    const next = e.target.checked

                      ? [...current, p]

                      : current.filter((x) => x !== p)

                    setForm({ ...form, enabled_platforms: next })

                  }}

                />

              }

              label={p}

            />

          ))}

        </Box>



        <TextField select fullWidth label="Catégorie YouTube" value={form.youtube_category_id} sx={{ mb: 3 }}

          onChange={(e) => setForm({ ...form, youtube_category_id: e.target.value })}>

          {YOUTUBE_CATEGORIES.map((c) => (

            <MenuItem key={c.id} value={c.id}>{c.id} — {c.label}</MenuItem>

          ))}

        </TextField>



        </>
      )}

      {tab === 1 && (
        <>

        <Typography variant="h6" sx={{ mb: 1 }}>Voix &amp; synthèse (TTS)</Typography>

        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>

          Choisissez le moteur et la voix séparément pour les shorts et les vidéos longues.

          Gemini nécessite une clé GOOGLE_GEMINI_API_KEY ; Azure nécessite AZURE_SPEECH_KEY.

        </Typography>



        <Typography variant="subtitle2" sx={{ mb: 1 }}>Shorts</Typography>

        <Box sx={{ display: 'flex', gap: 2, mb: 3 }}>

          <TextField select fullWidth label="Moteur" value={String(form.tts_short_engine || 'azure')}

            onChange={(e) => setForm({ ...form, tts_short_engine: e.target.value })}>

            {TTS_ENGINES.map((opt) => (

              <MenuItem key={opt.value} value={opt.value}>{opt.label}</MenuItem>

            ))}

          </TextField>

          <TextField select fullWidth label="Voix" value={String(form.tts_short_voice || '')}

            onChange={(e) => setForm({ ...form, tts_short_voice: e.target.value })}>

            {voiceOptionsForEngine(String(form.tts_short_engine || 'azure'), voices, geminiVoices).map((v) => (

              <MenuItem key={v.id} value={v.id}>{v.label}</MenuItem>

            ))}

          </TextField>

        </Box>



        <Typography variant="subtitle2" sx={{ mb: 1 }}>Vidéos longues</Typography>

        <Box sx={{ display: 'flex', gap: 2, mb: 3 }}>

          <TextField select fullWidth label="Moteur" value={String(form.tts_long_engine || 'azure')}

            onChange={(e) => setForm({ ...form, tts_long_engine: e.target.value })}>

            {TTS_ENGINES.map((opt) => (

              <MenuItem key={opt.value} value={opt.value}>{opt.label}</MenuItem>

            ))}

          </TextField>

          <TextField select fullWidth label="Voix" value={String(form.tts_long_voice || '')}

            onChange={(e) => setForm({ ...form, tts_long_voice: e.target.value })}>

            {voiceOptionsForEngine(String(form.tts_long_engine || 'azure'), voices, geminiVoices).map((v) => (

              <MenuItem key={v.id} value={v.id}>{v.label}</MenuItem>

            ))}

          </TextField>

        </Box>



        <TextField fullWidth label="Style expressif Azure (global)" value={String(form.tts_style || '')} sx={{ mb: 3 }}

          onChange={(e) => setForm({ ...form, tts_style: e.target.value })}

          helperText="Appliqué aux segments Azure : cheerful, empathetic, narration-professional… Le mood de chaque segment peut aussi varier le style." />

        </>
      )}

      {tab === 2 && (
        <>

        <Typography variant="h6" sx={{ mb: 1 }}>Générateur d&apos;images IA</Typography>

        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>

          Flux (fal.ai) et Google Imagen 3 uniquement — fallback quand les sources libres sont insuffisantes

        </Typography>



        <TextField select fullWidth label="Plan images IA" value={form.ai_plan} sx={{ mb: 2 }}

          onChange={(e) => {

            const plan = e.target.value

            const defaults = FALLBACK_OPTIONS[plan] || []

            setForm({

              ...form,

              ai_plan: plan,

              ai_fallback_chain: defaults[0] || '',

            })

          }}>

          {AI_PLANS.map((p) => (

            <MenuItem key={p.value} value={p.value}>{p.label}</MenuItem>

          ))}

        </TextField>



        {selectedPlan?.family && (

          <Chip label={selectedPlan.family} size="small" sx={{ mb: 2 }} />

        )}



        {form.ai_plan !== 'off' && (

          <>

            <TextField select fullWidth label="Fallback si échec" value={form.ai_fallback_chain} sx={{ mb: 2 }}

              onChange={(e) => setForm({ ...form, ai_fallback_chain: e.target.value })}>

              <MenuItem value="">Aucun</MenuItem>

              {(FALLBACK_OPTIONS[form.ai_plan as string] || []).map((p) => {

                const label = AI_PLANS.find((x) => x.value === p)?.label || p

                return <MenuItem key={p} value={p}>{label}</MenuItem>

              })}

            </TextField>



            <Box sx={{ display: 'flex', gap: 2, mb: 2, flexWrap: 'wrap' }}>

              <TextField type="number" label="Max img/segment" value={form.max_images_per_segment}

                onChange={(e) => setForm({ ...form, max_images_per_segment: e.target.value })} />

              <TextField type="number" label="Max img/vidéo" value={form.max_ai_images_per_video}

                onChange={(e) => setForm({ ...form, max_ai_images_per_video: e.target.value })} />

              <TextField type="number" label="Max img/semaine (opt.)" value={form.max_ai_images_per_week}

                onChange={(e) => setForm({ ...form, max_ai_images_per_week: e.target.value })} />

              <TextField type="number" label="Taux fallback % (opt.)" value={form.fallback_rate_override}

                inputProps={{ min: 0, max: 100, step: 1 }}

                helperText="Override niche — laisser vide pour auto"

                onChange={(e) => setForm({ ...form, fallback_rate_override: e.target.value })} />

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



        <Divider sx={{ my: 3 }} />

        <Typography variant="h6" sx={{ mb: 0.5 }}>Génération vidéo IA — Runway</Typography>

        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>

          Génère des clips vidéo B-roll via Runway Gen-4 quand aucune source stock ne suffit.

          Coût ~{runwayStatus?.cost_per_clip_usd?.toFixed(2) ?? '0.25'} $ par clip.

        </Typography>

        {runwayStatus?.credit_error && (

          <Alert severity="error" sx={{ mb: 2 }}>

            Runway a rejeté la dernière génération — crédits insuffisants sur votre compte.

            Rechargez vos crédits sur <strong>app.runwayml.com</strong>, l&apos;alerte disparaîtra automatiquement dans 24h.

          </Alert>

        )}

        <FormControlLabel

          control={

            <Switch

              checked={Boolean(form.runway_enabled)}

              onChange={(e) => setForm({ ...form, runway_enabled: e.target.checked })}

            />

          }

          label="Activer la génération vidéo Runway"

          sx={{ mb: 2, display: 'block' }}

        />

        {Boolean(form.runway_enabled) && (

          <Box sx={{ display: 'flex', gap: 2, mb: 2, flexWrap: 'wrap' }}>

            <TextField

              type="number"

              label="Budget mensuel ($)"

              value={form.runway_monthly_budget_usd}

              inputProps={{ min: 1, step: 1 }}

              helperText={runwayStatus ? `Dépensé ce mois : ${runwayStatus.spent_usd.toFixed(2)} $ / Restant : ${runwayStatus.remaining_usd.toFixed(2)} $` : ''}

              onChange={(e) => setForm({ ...form, runway_monthly_budget_usd: e.target.value })}

            />

            <TextField

              type="number"

              label="Max clips / vidéo"

              value={form.runway_max_clips_per_video}

              inputProps={{ min: 1, max: 10, step: 1 }}

              helperText="Clips Runway max par vidéo générée"

              onChange={(e) => setForm({ ...form, runway_max_clips_per_video: e.target.value })}

            />

          </Box>

        )}

        </>
      )}

    </PageContainer>

  )

}


