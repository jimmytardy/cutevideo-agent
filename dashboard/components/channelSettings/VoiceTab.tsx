'use client'

import Box from '@mui/material/Box'
import MenuItem from '@mui/material/MenuItem'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import useSWR from 'swr'

import { fetcher } from '@/lib/api'
import type { ChannelSettingsForm, UpdateChannelForm } from '@/lib/channelSettingsForm'
import { TTS_ENGINES, voiceOptionsForEngine, type Voice } from '@/lib/channelSettingsOptions'

interface Props {
  form: ChannelSettingsForm
  update: UpdateChannelForm
}

export default function VoiceTab({ form, update }: Props) {
  const { data: azureVoices } = useSWR<Voice[]>('/api/v1/config/tts/voices', fetcher)
  const { data: geminiVoices } = useSWR<Voice[]>('/api/v1/config/tts/gemini-voices', fetcher)

  return (
    <>
      <Typography variant="h6" sx={{ mb: 1 }}>Voix &amp; synthèse (TTS)</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Moteur et voix de la narration des Shorts. Gemini nécessite une clé GOOGLE_GEMINI_API_KEY ;
        Azure nécessite AZURE_SPEECH_KEY. Edge TTS est gratuit (voix Azure HD remplacées par une voix edge).
      </Typography>

      <Box sx={{ display: 'flex', gap: 2, mb: 3 }}>
        <TextField select fullWidth label="Moteur" value={form.tts_short_engine}
          onChange={(e) => update({ tts_short_engine: e.target.value })}>
          {TTS_ENGINES.map((opt) => <MenuItem key={opt.value} value={opt.value}>{opt.label}</MenuItem>)}
        </TextField>
        <TextField select fullWidth label="Voix" value={form.tts_short_voice}
          onChange={(e) => update({ tts_short_voice: e.target.value })}>
          {voiceOptionsForEngine(form.tts_short_engine, azureVoices, geminiVoices).map((v) => (
            <MenuItem key={v.id} value={v.id}>{v.label}</MenuItem>
          ))}
        </TextField>
      </Box>
    </>
  )
}
