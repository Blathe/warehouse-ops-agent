import { RefreshCwIcon } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'

import { BayDetails } from '@/components/floor/BayDetails'
import { FloorMap, type MapMode } from '@/components/floor/FloorMap'
import { STATUS_STYLES } from '@/components/floor/status'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { getFloorMap, type FloorMapData, type PickStatus } from '@/lib/api'
import { cn } from '@/lib/utils'

interface FloorMapPageProps {
  refreshKey?: number // change it to reload, e.g. after the agent or the crew changes stock
  highlight?: string[] // pick face codes the agent is working on
  selected: string | null // pick face code
  onSelect: (location: string) => void
}

const MODES: { value: MapMode; label: string }[] = [
  { value: 'status', label: 'Status' },
  { value: 'stock', label: 'Stock level' },
]

// The whole floor on one page: filter by zone, switch how the bays are coloured, click a bay
// for its stock. Selection lives in App so "Show on map" links elsewhere can set it.
export function FloorMapPage({
  refreshKey = 0,
  highlight = [],
  selected,
  onSelect,
}: FloorMapPageProps) {
  const [data, setData] = useState<FloorMapData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [zone, setZone] = useState<string>('all')
  const [mode, setMode] = useState<MapMode>('status')

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

  const zoneCodes = data ? [...new Set(data.bays.map((b) => b.zone))] : []
  const bays = data ? data.bays.filter((b) => zone === 'all' || b.zone === zone) : []
  const selectedBay = data?.bays.find((b) => b.pick.location === selected) ?? null

  return (
    <div className="flex w-full flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Floor map</h2>
          <p className="text-sm text-muted-foreground">
            Every pick face on the floor. Select a bay to see its stock and reserve pallets.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={load}>
          <RefreshCwIcon />
          Refresh
        </Button>
      </div>

      {error ? (
        <p className="text-sm text-destructive">Couldn't load the floor map: {error}</p>
      ) : !data ? (
        <div className="flex flex-col gap-3" role="status" aria-label="Loading floor map">
          <Skeleton className="h-8 w-80" />
          <Skeleton className="h-72 rounded-xl" />
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-4">
              <div role="group" aria-label="Zone" className="flex gap-1">
                {['all', ...zoneCodes].map((code) => (
                  <Button
                    key={code}
                    size="sm"
                    variant={zone === code ? 'secondary' : 'ghost'}
                    aria-pressed={zone === code}
                    onClick={() => setZone(code)}
                  >
                    {code === 'all' ? 'All zones' : `Zone ${code}`}
                  </Button>
                ))}
              </div>
              <div role="group" aria-label="Colour by" className="flex gap-1">
                {MODES.map(({ value, label }) => (
                  <Button
                    key={value}
                    size="sm"
                    variant={mode === value ? 'secondary' : 'ghost'}
                    aria-pressed={mode === value}
                    onClick={() => setMode(value)}
                  >
                    {label}
                  </Button>
                ))}
              </div>
            </div>
          </div>

          <Legend bays={bays} mode={mode} />

          <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_20rem]">
            <FloorMap
              bays={bays}
              mode={mode}
              highlight={highlight}
              selected={selected}
              onSelect={onSelect}
            />
            <div className="xl:sticky xl:top-0">
              {selectedBay ? (
                <BayDetails bay={selectedBay} />
              ) : (
                <p className="rounded-xl border border-dashed p-6 text-center text-sm text-muted-foreground">
                  Select a bay to see its stock.
                </p>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function Legend({ bays, mode }: { bays: FloorMapData['bays']; mode: MapMode }) {
  const counts: Record<PickStatus, number> = { ok: 0, low: 0, empty: 0, unassigned: 0 }
  for (const bay of bays) counts[bay.pick.status] += 1
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs" aria-label="Legend">
      {mode === 'status' ? (
        (Object.keys(STATUS_STYLES) as PickStatus[]).map((status) => (
          <li key={status} className="flex items-center gap-1.5">
            <span className={cn('size-3 rounded-[3px]', STATUS_STYLES[status].cell)} />
            {STATUS_STYLES[status].label} ({counts[status]})
          </li>
        ))
      ) : (
        <li className="flex items-center gap-2">
          <span>Empty</span>
          <span
            className="h-2.5 w-24 rounded-full"
            style={{
              background: 'linear-gradient(to right, var(--muted), var(--status-ok))',
            }}
          />
          <span>Full</span>
        </li>
      )}
      <li className="flex items-center gap-1.5">
        <span className="size-3 rounded-[3px] ring-2 ring-status-task ring-inset" />
        Open task
      </li>
      <li className="flex items-center gap-1.5">
        <span className="size-3 rounded-[3px] outline-2 outline-offset-1 outline-status-agent" />
        Agent is working here
      </li>
      <li className="flex items-center gap-1.5">
        <span className="relative size-3 rounded-[3px] bg-muted">
          <span className="absolute -top-0.5 -right-0.5 size-1.5 rounded-full bg-status-count" />
        </span>
        Open count discrepancy
      </li>
    </ul>
  )
}
