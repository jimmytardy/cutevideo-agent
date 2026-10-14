/** Formatage d'affichage (fr-FR) partagé par les pages du dashboard. */

const LOCALE = 'fr-FR'

/** « 14/10/2026 » */
export function formatDate(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleDateString(LOCALE) : '—'
}

/** « 14/10/2026 10:08:24 » */
export function formatDateTime(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString(LOCALE) : '—'
}

/** « 14/10 10:08 » */
export function formatShortDateTime(iso: string | null | undefined): string {
  return iso
    ? new Date(iso).toLocaleString(LOCALE, { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
    : '—'
}

/** Délai avant une échéance : « dans 12 min », « dans 3h », « Imminent ». */
export function formatRelativeFuture(iso: string | null | undefined): string {
  if (!iso) return 'Non planifié'
  const diffMin = Math.round((new Date(iso).getTime() - Date.now()) / 60000)
  if (diffMin < 0) return 'Imminent'
  if (diffMin < 60) return `dans ${diffMin} min`
  const diffH = Math.round(diffMin / 60)
  if (diffH < 24) return `dans ${diffH}h`
  return `dans ${Math.round(diffH / 24)}j`
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} o`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} Ko`
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} Mo`
  return `${(bytes / 1024 ** 3).toFixed(2)} Go`
}
