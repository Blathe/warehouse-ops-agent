import { MoonIcon, SunIcon } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { applyTheme, initialTheme, type Theme } from '@/lib/theme'

// Light/dark switch for the header. The choice is remembered in this browser.
export function ThemeToggle() {
  // Passing a function to useState runs it once, on the first render (a lazy initialiser).
  const [theme, setTheme] = useState<Theme>(initialTheme)

  function toggle() {
    const next = theme === 'dark' ? 'light' : 'dark'
    setTheme(next)
    applyTheme(next)
  }

  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
      onClick={toggle}
    >
      {theme === 'dark' ? <SunIcon /> : <MoonIcon />}
    </Button>
  )
}
