'use client'

import CssBaseline from '@mui/material/CssBaseline'
import { ThemeProvider } from '@mui/material/styles'
import { createAppTheme, THEME_STORAGE_KEY } from '@/lib/theme'

const theme = createAppTheme()

export default function ThemeRegistry({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider theme={theme} defaultMode="system" modeStorageKey={THEME_STORAGE_KEY}>
      <CssBaseline enableColorScheme />
      {children}
    </ThemeProvider>
  )
}
