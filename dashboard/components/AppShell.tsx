'use client'

import AppBar from '@mui/material/AppBar'
import Box from '@mui/material/Box'
import Drawer from '@mui/material/Drawer'
import List from '@mui/material/List'
import ListItemButton from '@mui/material/ListItemButton'
import ListItemIcon from '@mui/material/ListItemIcon'
import ListItemText from '@mui/material/ListItemText'
import Toolbar from '@mui/material/Toolbar'
import Typography from '@mui/material/Typography'
import HomeIcon from '@mui/icons-material/Home'
import VideoLibraryIcon from '@mui/icons-material/VideoLibrary'
import TvIcon from '@mui/icons-material/Tv'
import SmartToyIcon from '@mui/icons-material/SmartToy'
import BarChartIcon from '@mui/icons-material/BarChart'
import SettingsIcon from '@mui/icons-material/Settings'
import Link from 'next/link'
import { usePathname } from 'next/navigation'

const DRAWER_WIDTH = 220

const NAV_ITEMS = [
  { label: 'Accueil', href: '/', icon: <HomeIcon /> },
  { label: 'Chaînes', href: '/channels', icon: <TvIcon /> },
  { label: 'Projets', href: '/projects', icon: <VideoLibraryIcon /> },
  { label: 'Agents', href: '/agents', icon: <SmartToyIcon /> },
  { label: 'Analytics', href: '/analytics', icon: <BarChartIcon /> },
  { label: 'Config', href: '/config', icon: <SettingsIcon /> },
]

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()

  return (
    <Box sx={{ display: 'flex' }}>
      <AppBar
        position="fixed"
        sx={{ zIndex: (t) => t.zIndex.drawer + 1, bgcolor: 'background.paper' }}
        elevation={0}
      >
        <Toolbar>
          <Typography variant="h6" fontWeight={700} color="primary.main">
            🎬 CuteVideo Agent
          </Typography>
        </Toolbar>
      </AppBar>

      <Drawer
        variant="permanent"
        sx={{
          width: DRAWER_WIDTH,
          flexShrink: 0,
          '& .MuiDrawer-paper': {
            width: DRAWER_WIDTH,
            boxSizing: 'border-box',
            bgcolor: 'background.paper',
            borderRight: '1px solid rgba(255,255,255,0.08)',
          },
        }}
      >
        <Toolbar />
        <List dense sx={{ pt: 2 }}>
          {NAV_ITEMS.map((item) => (
            <ListItemButton
              key={item.href}
              component={Link}
              href={item.href}
              selected={pathname === item.href || (item.href !== '/' && pathname.startsWith(item.href))}
              sx={{
                mx: 1,
                borderRadius: 2,
                mb: 0.5,
                '&.Mui-selected': {
                  bgcolor: 'primary.dark',
                  '&:hover': { bgcolor: 'primary.dark' },
                },
              }}
            >
              <ListItemIcon sx={{ minWidth: 36, color: 'inherit' }}>{item.icon}</ListItemIcon>
              <ListItemText primary={item.label} />
            </ListItemButton>
          ))}
        </List>
      </Drawer>

      <Box component="main" sx={{ flexGrow: 1, p: 3 }}>
        <Toolbar />
        {children}
      </Box>
    </Box>
  )
}
