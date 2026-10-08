import { MapPinIcon, Trash2Icon } from 'lucide-react'

import { ActivityFeed } from '@/components/activity/ActivityFeed'
import type { ActivityItem } from '@/components/activity/activity'
import { Button } from '@/components/ui/button'

interface ActivityPanelProps {
  items: ActivityItem[]
  highlight: string[] // pick face codes the agent is working on
  onClear: () => void
  onShowOnMap: (location: string) => void
}

// What the agent has been doing, with a shortcut to the bay it is working on.
export function ActivityPanel({ items, highlight, onClear, onShowOnMap }: ActivityPanelProps) {
  return (
    <aside
      aria-labelledby="activity-heading"
      className="flex h-full min-h-0 min-w-0 flex-col gap-3 overflow-y-auto p-4"
    >
      <div className="flex items-center justify-between gap-2">
        <h2 id="activity-heading" className="text-sm font-semibold">
          Agent activity
        </h2>
        {items.length > 0 && (
          <Button variant="ghost" size="xs" aria-label="Clear agent activity" onClick={onClear}>
            <Trash2Icon />
            Clear
          </Button>
        )}
      </div>
      {highlight.length > 0 && (
        <Button
          variant="outline"
          size="sm"
          className="justify-start"
          onClick={() => onShowOnMap(highlight[0])}
        >
          <MapPinIcon />
          Show {highlight[0]} on the floor map
        </Button>
      )}
      <ActivityFeed items={items} />
    </aside>
  )
}
