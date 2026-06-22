'use client'

import { createTheme, type Theme } from '@mui/material/styles'
import { darkPalette, lightPalette } from './palette'

const sharedTypography = {
  fontFamily: 'var(--font-inter), "Inter", "Roboto", "Helvetica", "Arial", sans-serif',
  h4: { fontWeight: 700, letterSpacing: '-0.02em' },
  h5: { fontWeight: 600, letterSpacing: '-0.01em' },
  h6: { fontWeight: 600 },
  subtitle1: { fontWeight: 600 },
  button: { fontWeight: 600, textTransform: 'none' as const },
}

const sharedShape = {
  borderRadius: 10,
}

function componentOverrides(mode: 'light' | 'dark'): Theme['components'] {
  const cardBorder = mode === 'light' ? '1px solid #E2E8F0' : '1px solid rgba(255,255,255,0.08)'
  const cardShadow =
    mode === 'light'
      ? '0 1px 3px rgba(15, 23, 42, 0.06), 0 1px 2px rgba(15, 23, 42, 0.04)'
      : 'none'

  return {
    MuiCssBaseline: {
      styleOverrides: {
        body: {
          scrollbarColor: mode === 'light' ? '#CBD5E1 transparent' : '#334155 transparent',
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          border: cardBorder,
          boxShadow: cardShadow,
        },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: { fontWeight: 600 },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: { fontWeight: 600, textTransform: 'none', borderRadius: 8 },
      },
    },
    MuiListItemButton: {
      styleOverrides: {
        root: { borderRadius: 8 },
      },
    },
    MuiTableHead: {
      styleOverrides: {
        root: {
          '& .MuiTableCell-head': {
            fontWeight: 600,
            bgcolor: mode === 'light' ? '#F1F5F9' : 'rgba(255,255,255,0.04)',
          },
        },
      },
    },
    MuiAlert: {
      styleOverrides: {
        root: { borderRadius: 10 },
      },
    },
    MuiTextField: {
      defaultProps: {
        size: 'small' as const,
      },
    },
  }
}

export function createAppTheme(): Theme {
  return createTheme({
    cssVariables: {
      colorSchemeSelector: 'data',
    },
    colorSchemes: {
      light: {
        palette: lightPalette,
        components: componentOverrides('light'),
      },
      dark: {
        palette: darkPalette,
        components: componentOverrides('dark'),
      },
    },
    typography: sharedTypography,
    shape: sharedShape,
    components: {
      MuiChip: {
        styleOverrides: {
          root: { fontWeight: 600 },
        },
      },
      MuiButton: {
        styleOverrides: {
          root: { fontWeight: 600, textTransform: 'none', borderRadius: 8 },
        },
      },
    },
  })
}

/** @deprecated Use createAppTheme() — kept for backward compatibility */
export const theme = createAppTheme()
