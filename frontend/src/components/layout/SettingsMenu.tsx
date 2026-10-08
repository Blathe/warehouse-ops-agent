import { PauseIcon, PlayIcon, SettingsIcon } from 'lucide-react'

import { ModelPicker } from '@/components/ModelPicker'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { SidebarMenu, SidebarMenuButton, SidebarMenuItem } from '@/components/ui/sidebar'
import type { ModelOption } from '@/lib/api'

interface SettingsMenuProps {
  supervisor: string
  onSupervisorChange: (name: string) => void
  onSupervisorCommit: () => void // the name field lost focus: save it
  models: ModelOption[]
  model: string | null
  onModelChange: (id: string) => void
  simulating: boolean
  onToggleSimulation: () => void
}

// The sidebar's footer: who you are, with a popover for the settings that apply to the whole app.
export function SettingsMenu({
  supervisor,
  onSupervisorChange,
  onSupervisorCommit,
  models,
  model,
  onModelChange,
  simulating,
  onToggleSimulation,
}: SettingsMenuProps) {
  const name = supervisor.trim() || 'Supervisor'
  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <Popover>
          <PopoverTrigger asChild>
            <SidebarMenuButton size="lg" tooltip="Settings" aria-label="Settings">
              <span
                aria-hidden
                className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary text-sm font-medium text-primary-foreground"
              >
                {name.charAt(0).toUpperCase()}
              </span>
              <span className="grid min-w-0 flex-1 text-left leading-tight">
                <span className="truncate font-medium">{name}</span>
                <span className="truncate text-xs text-muted-foreground">Settings</span>
              </span>
              {simulating ? (
                <span aria-hidden className="size-2 shrink-0 animate-pulse rounded-full bg-status-ok" />
              ) : (
                <SettingsIcon aria-hidden className="ml-auto size-4 text-muted-foreground" />
              )}
            </SidebarMenuButton>
          </PopoverTrigger>
          <PopoverContent side="right" align="end" className="flex w-72 flex-col gap-4">
            <label className="flex flex-col gap-1.5 text-xs text-muted-foreground">
              Approving as
              <Input
                aria-label="Supervisor name"
                value={supervisor}
                onChange={(event) => onSupervisorChange(event.target.value)}
                onBlur={onSupervisorCommit}
                className="h-8"
              />
            </label>
            {model && models.length > 0 && (
              <label className="flex flex-col gap-1.5 text-xs text-muted-foreground">
                Chat model
                <ModelPicker models={models} value={model} onChange={onModelChange} />
              </label>
            )}
            <Button
              size="sm"
              variant={simulating ? 'secondary' : 'outline'}
              aria-pressed={simulating}
              title="Simulate the warehouse crew finishing one approved task every 5 seconds"
              onClick={onToggleSimulation}
              className="justify-start"
            >
              {simulating ? <PauseIcon /> : <PlayIcon />}
              Simulate crew
              {simulating && (
                <span aria-hidden className="ml-auto size-2 animate-pulse rounded-full bg-status-ok" />
              )}
            </Button>
          </PopoverContent>
        </Popover>
      </SidebarMenuItem>
    </SidebarMenu>
  )
}
