export const brandColors = {
  primary: {
    light: { main: '#6D28D9', light: '#8B5CF6', dark: '#5B21B6', contrastText: '#FFFFFF' },
    dark: { main: '#8B5CF6', light: '#A78BFA', dark: '#6D28D9', contrastText: '#FFFFFF' },
  },
  secondary: {
    light: { main: '#0891B2', light: '#22D3EE', dark: '#0E7490', contrastText: '#FFFFFF' },
    dark: { main: '#22D3EE', light: '#67E8F9', dark: '#0891B2', contrastText: '#0F172A' },
  },
  success: { main: '#10B981' },
  error: { main: '#EF4444' },
  warning: { main: '#F59E0B' },
  info: { main: '#3B82F6' },
} as const

export const lightPalette = {
  mode: 'light' as const,
  primary: brandColors.primary.light,
  secondary: brandColors.secondary.light,
  success: brandColors.success,
  error: brandColors.error,
  warning: brandColors.warning,
  info: brandColors.info,
  background: {
    default: '#F8FAFC',
    paper: '#FFFFFF',
  },
  text: {
    primary: '#0F172A',
    secondary: '#64748B',
  },
  divider: '#E2E8F0',
}

export const darkPalette = {
  mode: 'dark' as const,
  primary: brandColors.primary.dark,
  secondary: brandColors.secondary.dark,
  success: brandColors.success,
  error: brandColors.error,
  warning: brandColors.warning,
  info: brandColors.info,
  background: {
    default: '#0B1120',
    paper: '#151B2E',
  },
  text: {
    primary: '#F1F5F9',
    secondary: '#94A3B8',
  },
  divider: 'rgba(255,255,255,0.08)',
}

export const THEME_STORAGE_KEY = 'cutevideo-theme-mode'

export type ThemeMode = 'light' | 'dark' | 'system'
