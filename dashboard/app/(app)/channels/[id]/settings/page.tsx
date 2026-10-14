'use client'

import { useState, useEffect, useMemo } from 'react'
import useSWR from 'swr'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import CircularProgress from '@mui/material/CircularProgress'
import Tab from '@mui/material/Tab'
import Tabs from '@mui/material/Tabs'

import AiMediaTab from '@/components/channelSettings/AiMediaTab'
import GeneralTab from '@/components/channelSettings/GeneralTab'
import VoiceTab from '@/components/channelSettings/VoiceTab'
import { PageContainer, PageHeader, LoadingState, useConfirmDialog } from '@/components/layout'
import TikTokPublishingPanel from '@/components/TikTokPublishingPanel'
import { fetcher, previewChannelCostEstimate, updateChannel, type Channel, type ChannelCostEstimate } from '@/lib/api'
import {
  aiFallbackPayload,
  buildChannelUpdatePayload,
  channelSettingsFormsEqual,
  channelToFormState,
  type ChannelSettingsForm,
  type UpdateChannelForm,
} from '@/lib/channelSettingsForm'
import { useUnsavedChangesWarning } from '@/lib/useUnsavedChangesWarning'

interface Props {
  params: { id: string }
}

export default function ChannelSettingsPage({ params }: Props) {
  const { id } = params
  const { data: channel, isLoading, mutate } = useSWR<Channel>(`/api/v1/channels/${id}`, fetcher)
  const [form, setForm] = useState<ChannelSettingsForm | null>(null)
  const [savedForm, setSavedForm] = useState<ChannelSettingsForm | null>(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [costEstimate, setCostEstimate] = useState<ChannelCostEstimate | null>(null)
  const [tab, setTab] = useState(0)
  const { confirm, dialog: leaveConfirmDialog } = useConfirmDialog()

  const isDirty = useMemo(
    () => Boolean(form && savedForm && !channelSettingsFormsEqual(form, savedForm)),
    [form, savedForm],
  )
  useUnsavedChangesWarning(isDirty, confirm)

  useEffect(() => {
    if (!channel || form) return
    const initialForm = channelToFormState(channel)
    setForm(initialForm)
    setSavedForm(initialForm)
  }, [channel, form])

  // Aperçu du coût IA hebdomadaire, recalculé (avec anti-rebond) à chaque modification.
  useEffect(() => {
    if (!form) return
    const timer = setTimeout(() => {
      previewChannelCostEstimate(id, { ai_fallback: aiFallbackPayload(form) })
        .then(setCostEstimate)
        .catch(() => { /* aperçu optionnel */ })
    }, 300)
    return () => clearTimeout(timer)
  }, [form, id])

  const update: UpdateChannelForm = (patch) => setForm((current) => (current ? { ...current, ...patch } : current))

  const handleSave = async () => {
    if (!form || !channel) return
    setSaving(true)
    setSaveError(null)
    try {
      const updated = await updateChannel(id, buildChannelUpdatePayload(form, channel))
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
        <Tab label="Publication" />
      </Tabs>

      {tab === 0 && <GeneralTab form={form} update={update} />}
      {tab === 1 && <VoiceTab form={form} update={update} />}
      {tab === 2 && <AiMediaTab form={form} update={update} costEstimate={costEstimate} />}
      {tab === 3 && <TikTokPublishingPanel channelId={id} />}
    </PageContainer>
  )
}
