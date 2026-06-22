'use client'

import { useState } from 'react'
import IconButton from '@mui/material/IconButton'
import Menu from '@mui/material/Menu'
import MenuItem from '@mui/material/MenuItem'
import ListItemIcon from '@mui/material/ListItemIcon'
import ListItemText from '@mui/material/ListItemText'
import Tooltip from '@mui/material/Tooltip'
import LightModeOutlinedIcon from '@mui/icons-material/LightModeOutlined'
import DarkModeOutlinedIcon from '@mui/icons-material/DarkModeOutlined'
import SettingsBrightnessOutlinedIcon from '@mui/icons-material/SettingsBrightnessOutlined'
import CheckIcon from '@mui/icons-material/Check'
import { useColorScheme } from '@mui/material/styles'
import type { ThemeMode } from '@/lib/theme'

const MODE_OPTIONS: { value: ThemeMode; label: string; icon: React.ReactNode }[] = [
  { value: 'light', label: 'Clair', icon: <LightModeOutlinedIcon fontSize="small" /> },
  { value: 'dark', label: 'Sombre', icon: <DarkModeOutlinedIcon fontSize="small" /> },
  { value: 'system', label: 'Système', icon: <SettingsBrightnessOutlinedIcon fontSize="small" /> },
]

export default function ThemeToggle() {
  const { mode, setMode } = useColorScheme()
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null)
  const open = Boolean(anchorEl)
  const currentMode = (mode ?? 'system') as ThemeMode

  return (
    <>
      <Tooltip title="Thème d'affichage">
        <IconButton
          size="small"
          onClick={(e) => setAnchorEl(e.currentTarget)}
          aria-label="Changer le thème"
          aria-controls={open ? 'theme-menu' : undefined}
          aria-haspopup="true"
        >
          {currentMode === 'dark' ? (
            <DarkModeOutlinedIcon fontSize="small" />
          ) : currentMode === 'light' ? (
            <LightModeOutlinedIcon fontSize="small" />
          ) : (
            <SettingsBrightnessOutlinedIcon fontSize="small" />
          )}
        </IconButton>
      </Tooltip>
      <Menu
        id="theme-menu"
        anchorEl={anchorEl}
        open={open}
        onClose={() => setAnchorEl(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
      >
        {MODE_OPTIONS.map((option) => (
          <MenuItem
            key={option.value}
            selected={currentMode === option.value}
            onClick={() => {
              setMode(option.value)
              setAnchorEl(null)
            }}
          >
            <ListItemIcon>{option.icon}</ListItemIcon>
            <ListItemText>{option.label}</ListItemText>
            {currentMode === option.value && (
              <CheckIcon fontSize="small" sx={{ ml: 1, opacity: 0.7 }} />
            )}
          </MenuItem>
        ))}
      </Menu>
    </>
  )
}
