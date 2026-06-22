'use client'

import CssBaseline from '@mui/material/CssBaseline'
import { ThemeProvider } from '@mui/material/styles'
import { createAppTheme } from '@/lib/theme'

const theme = createAppTheme()

export default function ThemeRegistry({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider theme={theme} defaultMode="system" modeStorageKey="cutevideo-theme-mode">
      <CssBaseline enableColorScheme />
      {children}
    </ThemeProvider>
  )
}
