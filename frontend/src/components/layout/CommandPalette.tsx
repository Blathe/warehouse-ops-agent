import { MoonIcon, PauseIcon, PlayIcon, SunIcon } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'

import { STATUS_STYLES } from '@/components/floor/status'
import { PAGES } from '@/components/layout/pages'
import {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandShortcut,
} from '@/components/ui/command'
import { getFloorMap, type Bay } from '@/lib/api'
import { applyTheme, useCurrentTheme } from '@/lib/theme'
import { cn } from '@/lib/utils'

interface CommandPaletteProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onShowOnMap: (location: string) => void // pick face code to show on the floor map
  simulating: boolean
  onToggleSimulation: () => void
}

// Ctrl/Cmd+K: jump to a page, flip a switch, or find a pick face by location, SKU or name.
export function CommandPalette({
  open,
  onOpenChange,
  onShowOnMap,
  simulating,
  onToggleSimulation,
}: CommandPaletteProps) {
  const navigate = useNavigate()
  const theme = useCurrentTheme()
  const [bays, setBays] = useState<Bay[]>([])

  // The shortcut works from anywhere in the app. (The cleanup removes the listener again.)
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key.toLowerCase() === 'k' && (event.metaKey || event.ctrlKey)) {
        event.preventDefault()
        onOpenChange(!open)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open, onOpenChange])

  // Load the pick faces each time the palette opens, so stock levels are current.
  useEffect(() => {
    if (!open) return
    getFloorMap()
      .then((map) => setBays(map.bays.filter((bay) => bay.pick.sku_code)))
      .catch(() => setBays([]))
  }, [open])

  // Run a command, then close the palette.
  function run(action: () => void) {
    onOpenChange(false)
    action()
  }

  return (
    <CommandDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Command palette"
      description="Go to a page, run an action or find a pick face"
    >
      <Command>
        <CommandInput placeholder="Go to a page, or search a location, SKU or product..." />
        <CommandList>
          <CommandEmpty>Nothing matches that.</CommandEmpty>
          <CommandGroup heading="Go to">
            {PAGES.map(({ path, title, icon: Icon }) => (
              <CommandItem key={path} value={`page ${title}`} onSelect={() => run(() => navigate(path))}>
                <Icon />
                {title}
              </CommandItem>
            ))}
          </CommandGroup>
          <CommandGroup heading="Actions">
            <CommandItem
              value="action toggle dark light theme"
              onSelect={() => run(() => applyTheme(theme === 'dark' ? 'light' : 'dark'))}
            >
              {theme === 'dark' ? <SunIcon /> : <MoonIcon />}
              {theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            </CommandItem>
            <CommandItem value="action simulate crew" onSelect={() => run(onToggleSimulation)}>
              {simulating ? <PauseIcon /> : <PlayIcon />}
              {simulating ? 'Stop the crew simulation' : 'Start the crew simulation'}
            </CommandItem>
          </CommandGroup>
          {bays.length > 0 && (
            <CommandGroup heading="Pick faces">
              {bays.map(({ pick }) => (
                <CommandItem
                  key={pick.location}
                  value={`face ${pick.location} ${pick.sku_code} ${pick.description}`}
                  onSelect={() => run(() => onShowOnMap(pick.location))}
                >
                  <span className={cn('size-2.5 shrink-0 rounded-sm', STATUS_STYLES[pick.status].cell)} />
                  <span className="font-medium">{pick.location}</span>
                  <span className="truncate text-muted-foreground">{pick.description}</span>
                  <CommandShortcut>{pick.on_hand} on hand</CommandShortcut>
                </CommandItem>
              ))}
            </CommandGroup>
          )}
        </CommandList>
      </Command>
    </CommandDialog>
  )
}
