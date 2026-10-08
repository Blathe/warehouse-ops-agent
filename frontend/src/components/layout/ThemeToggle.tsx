import { MoonIcon, SunIcon } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { applyTheme, useCurrentTheme } from '@/lib/theme'

// Light/dark switch for the header. The choice is remembered in this browser.
export function ThemeToggle() {
  // Read from the page itself, so the command palette flipping the theme updates this too.
  const theme = useCurrentTheme()

  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
      onClick={() => applyTheme(theme === 'dark' ? 'light' : 'dark')}
    >
      {theme === 'dark' ? <SunIcon /> : <MoonIcon />}
    </Button>
  )
}
