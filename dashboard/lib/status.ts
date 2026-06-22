export type ProjectStatus =
  | 'pending'
  | 'queued'
  | 'running'
  | 'review'
  | 'approved'
  | 'rejected'
  | 'published'
  | 'failed'
  | 'stopped'

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
