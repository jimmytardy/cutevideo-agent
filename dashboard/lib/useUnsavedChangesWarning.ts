'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'

type ConfirmFn = (options: {
  title: string
  message: string
  confirmLabel?: string
  cancelLabel?: string
  confirmColor?: 'primary' | 'error' | 'warning'
}) => Promise<boolean>

const DEFAULT_MESSAGE =
  'Vous avez des modifications non enregistrées. Quitter cette page sans enregistrer ?'

export function useUnsavedChangesWarning(isDirty: boolean, confirm: ConfirmFn) {
  const router = useRouter()

  useEffect(() => {
    if (!isDirty) return

    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }

    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [isDirty])

  useEffect(() => {
    if (!isDirty) return

    const onClick = (event: MouseEvent) => {
      if (event.defaultPrevented) return
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
        return
      }

      const anchor = (event.target as HTMLElement).closest('a')
      if (!anchor) return

      const href = anchor.getAttribute('href')
      if (!href || href.startsWith('#') || anchor.target === '_blank') return

      const isExternal = href.startsWith('http') && !href.startsWith(window.location.origin)
      if (isExternal) return

      event.preventDefault()
      event.stopPropagation()

      void confirm({
        title: 'Modifications non enregistrées',
        message: DEFAULT_MESSAGE,
        confirmLabel: 'Quitter sans enregistrer',
        cancelLabel: 'Rester sur la page',
        confirmColor: 'warning',
      }).then((shouldLeave) => {
        if (!shouldLeave) return
        if (href.startsWith('/')) {
          router.push(href)
        } else {
          window.location.assign(href)
        }
      })
    }

    document.addEventListener('click', onClick, true)
    return () => document.removeEventListener('click', onClick, true)
  }, [isDirty, confirm, router])
}
