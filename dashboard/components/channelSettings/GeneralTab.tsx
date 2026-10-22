'use client'

import Box from '@mui/material/Box'
import Checkbox from '@mui/material/Checkbox'
import FormControlLabel from '@mui/material/FormControlLabel'
import MenuItem from '@mui/material/MenuItem'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'

import { WORDS_PER_SECOND_RANGE, wordsPerSecond } from '@/lib/channelSettingsForm'
import type { ChannelSettingsForm, UpdateChannelForm } from '@/lib/channelSettingsForm'
import { ANIMATION_MODES, PLATFORMS, PRODUCTION_MODES, VISUAL_STYLES, YOUTUBE_CATEGORIES } from '@/lib/channelSettingsOptions'

interface Props {
  form: ChannelSettingsForm
  update: UpdateChannelForm
}

export default function GeneralTab({ form, update }: Props) {
  const wpsInvalid = String(form.words_per_second).trim() !== '' && wordsPerSecond(form) === null
  const togglePlatform = (platform: string, enabled: boolean) => {
    const current = form.enabled_platforms
    update({ enabled_platforms: enabled ? [...current, platform] : current.filter((p) => p !== platform) })
  }

  return (
    <>
      <TextField fullWidth label="Catégorie / thème" value={form.theme_category} sx={{ mb: 2 }}
        onChange={(e) => update({ theme_category: e.target.value })}
        helperText="Valeur libre — ex: histoire, science, true_crime, cuisine…" />

      <TextField fullWidth label="Thème chaîne (theme_prompt)" multiline rows={2}
        value={form.theme_prompt} sx={{ mb: 2 }}
        onChange={(e) => update({ theme_prompt: e.target.value })} />

      <TextField fullWidth label="Niche (niche_prompt)" multiline rows={2}
        value={form.niche_prompt} sx={{ mb: 2 }}
        onChange={(e) => update({ niche_prompt: e.target.value })} />

      <TextField fullWidth label="Brief créatif" multiline rows={6}
        value={form.creative_brief} sx={{ mb: 2 }}
        onChange={(e) => update({ creative_brief: e.target.value })}
        placeholder="Décris le ton, le style narratif, les thèmes récurrents, ce qui distingue la chaîne, les interdits éditoriaux…"
        helperText="Transmis à Claude Studio (brief.json) : le scénariste et le critique le respectent" />

      <TextField fullWidth label="Ton éditorial" value={form.tone} sx={{ mb: 2 }}
        onChange={(e) => update({ tone: e.target.value })}
        helperText="Ex: Humoristique, léger — influence scénario et voix" />

      <TextField select fullWidth label="Mode production" value={form.production_mode} sx={{ mb: 2 }}
        onChange={(e) => update({ production_mode: e.target.value })}>
        {PRODUCTION_MODES.map((m) => <MenuItem key={m.value} value={m.value}>{m.label}</MenuItem>)}
      </TextField>

      <TextField select fullWidth label="Animations (Claude Studio)" value={form.animations} sx={{ mb: 2 }}
        helperText="Scripts libres : Claude écrit ses propres animations (HTML/JS, Python) dans un bac à sable isolé, comme sur claude.ai."
        onChange={(e) => update({ animations: e.target.value })}>
        {ANIMATION_MODES.map((m) => <MenuItem key={m.value} value={m.value}>{m.label}</MenuItem>)}
      </TextField>

      <TextField select fullWidth label="Style visuel" value={form.visual_style} sx={{ mb: 2 }}
        helperText="Mixte / Réaliste : photos et vidéos libres (Pexels, Pixabay, Unsplash…) avec crédits ; imposé au scénariste et au monteur."
        onChange={(e) => update({ visual_style: e.target.value })}>
        {VISUAL_STYLES.map((m) => <MenuItem key={m.value} value={m.value}>{m.label}</MenuItem>)}
      </TextField>

      <Box sx={{ display: 'flex', gap: 2, mb: 2, flexWrap: 'wrap' }}>
        <TextField type="number" label="Quota longues/j" value={form.long_quota}
          onChange={(e) => update({ long_quota: e.target.value })} />
        <TextField type="number" label="Quota shorts/j" value={form.short_quota}
          onChange={(e) => update({ short_quota: e.target.value })} />
        <TextField type="number" label="Durée short cible (s)" value={form.short_duration_s}
          helperText="Plafonnée par l'abonnement"
          onChange={(e) => update({ short_duration_s: e.target.value })} />
        <TextField type="number" label="Débit conseillé (mots/s)" value={form.words_per_second}
          placeholder="3.1" error={wpsInvalid}
          helperText={wpsInvalid
            ? 'Nombre attendu, par ex. 2.8'
            : `Repère pour le script et la voix, de ${WORDS_PER_SECOND_RANGE.min} à ${WORDS_PER_SECOND_RANGE.max} (vide = défaut)`}
          inputProps={{ step: 0.1, ...WORDS_PER_SECOND_RANGE }}
          onChange={(e) => update({ words_per_second: e.target.value })} />
      </Box>

      <Typography variant="subtitle2" sx={{ mb: 1 }}>Plateformes actives</Typography>
      <Box sx={{ mb: 2 }}>
        {PLATFORMS.map((p) => (
          <FormControlLabel
            key={p}
            label={p}
            control={(
              <Checkbox
                checked={form.enabled_platforms.includes(p)}
                onChange={(e) => togglePlatform(p, e.target.checked)}
              />
            )}
          />
        ))}
      </Box>

      <TextField select fullWidth label="Catégorie YouTube" value={form.youtube_category_id} sx={{ mb: 3 }}
        onChange={(e) => update({ youtube_category_id: e.target.value })}>
        {YOUTUBE_CATEGORIES.map((c) => (
          <MenuItem key={c.value} value={c.value}>{c.value} — {c.label}</MenuItem>
        ))}
      </TextField>
    </>
  )
}
