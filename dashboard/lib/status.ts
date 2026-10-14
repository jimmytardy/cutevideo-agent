export type StatusChipColor = 'default' | 'warning' | 'info' | 'success' | 'error'

const PROJECT_STATUS_LABELS: Record<string, string> = {
  pending: 'En attente',
  queued: 'En file d\'attente',
  running: 'En cours',
  review: 'En revue',
  approved: 'Approuvé',
  rejected: 'Rejeté',
  published: 'Publié',
  failed: 'Échoué',
  stopped: 'Arrêté',
}

const PROJECT_STATUS_COLORS: Record<string, StatusChipColor> = {
  pending: 'warning',
  queued: 'default',
  running: 'info',
  review: 'info',
  approved: 'success',
  rejected: 'error',
  published: 'success',
  failed: 'error',
  stopped: 'warning',
}

export function projectStatusLabel(status: string): string {
  return PROJECT_STATUS_LABELS[status] ?? status
}

export function projectStatusColor(status: string): StatusChipColor {
  return PROJECT_STATUS_COLORS[status] ?? 'default'
}

/** Statut d'une exécution (AgentRun, job du scheduler). */
const RUN_STATUS_LABELS: Record<string, string> = {
  running: 'En cours',
  success: 'Terminé',
  failed: 'Échec',
  stopped: 'Arrêté',
  pending: 'En attente',
  skipped: 'Ignoré',
}

const RUN_STATUS_COLORS: Record<string, StatusChipColor> = {
  running: 'warning',
  success: 'success',
  failed: 'error',
}

export function runStatusLabel(status: string | null | undefined): string {
  return status ? RUN_STATUS_LABELS[status] ?? status : ''
}

export function runStatusColor(status: string | null | undefined): StatusChipColor {
  return (status && RUN_STATUS_COLORS[status]) || 'default'
}
