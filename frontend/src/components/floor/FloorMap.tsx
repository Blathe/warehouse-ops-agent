import { RefreshCwIcon } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'

import { BayDetails } from '@/components/floor/BayDetails'
import { STATUS_STYLES } from '@/components/floor/status'
import { Button } from '@/components/ui/button'
import { getFloorMap, type Bay, type FloorMapData, type PickStatus } from '@/lib/api'
import { cn } from '@/lib/utils'

const ZONE_NAMES: Record<string, string> = {
  A: 'Zone A: small tackle',
  B: 'Zone B: rods & reels',
  C: 'Zone C: bulky gear',
}

// Groups bays into rows: one row per aisle, bays left to right.
function aisles(bays: Bay[]): { zone: string; aisle: number; bays: Bay[] }[] {
  const rows = new Map<string, { zone: string; aisle: number; bays: Bay[] }>()
  for (const bay of bays) {
    const key = `${bay.zone}-${bay.aisle}`
    if (!rows.has(key)) rows.set(key, { zone: bay.zone, aisle: bay.aisle, bays: [] })
    rows.get(key)!.bays.push(bay)
  }
  return [...rows.values()]
}

interface FloorMapProps {
  refreshKey?: number // change it to reload, e.g. after the agent finishes a turn
  highlight?: string[] // pick face codes the agent is working on
  selected?: string | null // pick face code; pass with onSelect to control selection
  onSelect?: (location: string) => void
}

export function FloorMap({ refreshKey = 0, highlight = [], selected, onSelect }: FloorMapProps) {
  const [data, setData] = useState<FloorMapData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [ownSelection, setOwnSelection] = useState<string | null>(null)
  const current = selected !== undefined ? selected : ownSelection
  const select = onSelect ?? setOwnSelection

  const load = useCallback(() => {
    getFloorMap()
      .then((map) => {
        setData(map)
        setError(null)
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  // Reload when shown and whenever refreshKey changes; the Refresh button calls load too.
  useEffect(load, [load, refreshKey])

  if (error) return <p className="p-4 text-sm text-destructive">Couldn't load the floor map: {error}</p>
  if (!data) return <p className="p-4 text-sm text-muted-foreground">Loading floor map...</p>

  const rows = aisles(data.bays)
  const selectedBay = data.bays.find((b) => b.pick.location === current) ?? null
  const highlighted = new Set(highlight)

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <ul className="flex flex-wrap gap-x-3 gap-y-1 text-xs" aria-label="Legend">
          {(Object.keys(STATUS_STYLES) as PickStatus[]).map((status) => (
            <li key={status} className="flex items-center gap-1.5">
              <span className={cn('size-3 rounded-sm', STATUS_STYLES[status].cell)} />
              {STATUS_STYLES[status].label} ({data.counts[status]})
            </li>
          ))}
          <li className="flex items-center gap-1.5">
            <span className="size-3 rounded-sm ring-2 ring-blue-500 ring-inset" />
            Open task
          </li>
          <li className="flex items-center gap-1.5">
            <span className="size-3 rounded-sm outline-2 outline-offset-1 outline-violet-500" />
            Agent is working here
          </li>
        </ul>
        <Button variant="outline" size="sm" onClick={load}>
          <RefreshCwIcon />
          Refresh
        </Button>
      </div>

      <div className="overflow-x-auto pb-2">
        <div className="flex w-max flex-col gap-0.5">
          {rows.map((row, index) => (
            <div key={`${row.zone}-${row.aisle}`}>
              {(index === 0 || rows[index - 1].zone !== row.zone) && (
                <h3 className="mt-2 mb-1 text-xs font-medium text-muted-foreground">
                  {ZONE_NAMES[row.zone] ?? `Zone ${row.zone}`}
                </h3>
              )}
              <div className="flex items-center gap-0.5">
                <span className="w-12 shrink-0 text-[11px] text-muted-foreground">
                  Aisle {row.aisle}
                </span>
                {row.bays.map((bay) => (
                  <BayCell
                    key={bay.pick.location}
                    bay={bay}
                    selected={bay.pick.location === current}
                    highlighted={highlighted.has(bay.pick.location)}
                    onSelect={() => select(bay.pick.location)}
                  />
                ))}
              </div>
            </div>
          ))}
          <p className="mt-1 pl-12 text-[11px] text-muted-foreground">
            Bay 1 (dock end, fastest movers) on the left to bay {rows[0]?.bays.length} on the right
          </p>
        </div>
      </div>

      {selectedBay ? (
        <BayDetails bay={selectedBay} />
      ) : (
        <p className="text-sm text-muted-foreground">Select a bay to see its stock.</p>
      )}
    </div>
  )
}

function BayCell({
  bay,
  selected,
  highlighted,
  onSelect,
}: {
  bay: Bay
  selected: boolean
  highlighted: boolean
  onSelect: () => void
}) {
  const { pick } = bay
  const label = [
    pick.location,
    STATUS_STYLES[pick.status].label,
    pick.sku_code ? `SKU ${pick.sku_code}, ${pick.on_hand} on hand` : null,
    pick.open_task_id ? `open task #${pick.open_task_id}` : null,
  ]
    .filter(Boolean)
    .join(', ')
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      aria-pressed={selected}
      onClick={onSelect}
      className={cn(
        'size-3.5 shrink-0 rounded-sm transition-transform hover:scale-125 focus-visible:outline-2 focus-visible:outline-ring',
        STATUS_STYLES[pick.status].cell,
        pick.open_task_id && 'ring-2 ring-blue-500 ring-inset',
        highlighted && 'animate-pulse outline-2 outline-offset-1 outline-violet-500',
        selected && 'scale-125 outline-2 outline-foreground',
      )}
    />
  )
}
