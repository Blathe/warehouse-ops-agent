import { STATUS_STYLES, ZONE_NAMES } from '@/components/floor/status'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import type { Bay, PickStatus } from '@/lib/api'
import { cn } from '@/lib/utils'

// "status" colours each pick face by empty / low / ok; "stock" shades it by how full it is.
export type MapMode = 'status' | 'stock'

interface Aisle {
  aisle: number
  bays: Bay[]
}

// Groups bays into zones, and each zone into aisles (one row per aisle, bays left to right).
function zones(bays: Bay[]): { zone: string; aisles: Aisle[] }[] {
  const byZone = new Map<string, Map<number, Bay[]>>()
  for (const bay of bays) {
    const aisles = byZone.get(bay.zone) ?? new Map<number, Bay[]>()
    aisles.set(bay.aisle, [...(aisles.get(bay.aisle) ?? []), bay])
    byZone.set(bay.zone, aisles)
  }
  return [...byZone].map(([zone, aisles]) => ({
    zone,
    aisles: [...aisles].map(([aisle, bays]) => ({ aisle, bays })),
  }))
}

interface FloorMapProps {
  bays: Bay[] // the bays to draw (the page filters by zone first)
  mode: MapMode
  highlight: string[] // pick face codes the agent is working on
  selected: string | null // pick face code
  onSelect: (location: string) => void
}

// The warehouse floor: one block per zone with the dock on its left and an aisle per row.
export function FloorMap({ bays, mode, highlight, selected, onSelect }: FloorMapProps) {
  const highlighted = new Set(highlight)
  return (
    // The provider is here (not only in App) so the map also works on its own, e.g. in tests.
    <TooltipProvider delayDuration={80}>
      <div className="flex flex-col gap-4">
        {zones(bays).map(({ zone, aisles }) => (
          <section
            key={zone}
            aria-label={ZONE_NAMES[zone] ?? `Zone ${zone}`}
            className="rounded-xl border bg-card p-3 text-card-foreground"
          >
            <ZoneHeader zone={zone} bays={aisles.flatMap((a) => a.bays)} />
            <div className="flex gap-3">
              <div
                aria-hidden
                className="flex w-6 shrink-0 items-center justify-center rounded-md border border-dashed bg-muted/60 text-[10px] font-medium tracking-[0.3em] text-muted-foreground uppercase [writing-mode:vertical-rl]"
              >
                Dock
              </div>
              <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                {aisles.map((row) => (
                  <div key={row.aisle} className="flex items-center gap-2">
                    <span className="w-12 shrink-0 text-[11px] text-muted-foreground">
                      Aisle {row.aisle}
                    </span>
                    <div
                      className="grid flex-1 gap-[3px]"
                      style={{ gridTemplateColumns: `repeat(${row.bays.length}, minmax(14px, 1fr))` }}
                    >
                      {row.bays.map((bay) => (
                        <BayCell
                          key={bay.pick.location}
                          bay={bay}
                          mode={mode}
                          selected={bay.pick.location === selected}
                          highlighted={highlighted.has(bay.pick.location)}
                          onSelect={() => onSelect(bay.pick.location)}
                        />
                      ))}
                    </div>
                  </div>
                ))}
                <p className="pl-14 text-[11px] text-muted-foreground">
                  Bay 1 at the dock end (fastest movers) to bay {aisles[0]?.bays.length} at the far
                  end
                </p>
              </div>
            </div>
          </section>
        ))}
      </div>
    </TooltipProvider>
  )
}

function ZoneHeader({ zone, bays }: { zone: string; bays: Bay[] }) {
  const refill = bays.filter((b) => b.pick.status === 'empty' || b.pick.status === 'low').length
  return (
    <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
      <h3 className="text-sm font-semibold">{ZONE_NAMES[zone] ?? `Zone ${zone}`}</h3>
      <span className="text-xs text-muted-foreground tabular-nums">
        {refill === 0 ? 'All pick faces stocked' : `${refill} need refilling`}
      </span>
    </div>
  )
}

// Fill level of a pick face as a 0..1 share of its max.
function fill(bay: Bay): number {
  const { on_hand, max_qty } = bay.pick
  return max_qty ? Math.min(1, on_hand / max_qty) : 0
}

function BayCell({
  bay,
  mode,
  selected,
  highlighted,
  onSelect,
}: {
  bay: Bay
  mode: MapMode
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
    bay.open_discrepancies.length > 0
      ? `count discrepancy at ${bay.open_discrepancies.join(' and ')}`
      : null,
  ]
    .filter(Boolean)
    .join(', ')
  const shaded = mode === 'stock' && pick.status !== 'unassigned'
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={label}
          aria-pressed={selected}
          onClick={onSelect}
          // Stock view mixes the "ok" colour into the background in proportion to the fill.
          style={
            shaded
              ? {
                  backgroundColor: `color-mix(in oklab, var(--status-ok) ${Math.round(fill(bay) * 100)}%, var(--muted))`,
                }
              : undefined
          }
          className={cn(
            'relative aspect-square w-full rounded-[4px] transition-transform hover:z-10 hover:scale-125 focus-visible:z-10 focus-visible:outline-2 focus-visible:outline-ring',
            !shaded && STATUS_STYLES[pick.status].cell,
            pick.open_task_id && 'ring-2 ring-status-task ring-inset',
            highlighted && 'animate-pulse outline-2 outline-offset-1 outline-status-agent',
            selected && 'z-10 scale-125 outline-2 outline-foreground',
          )}
        >
          {bay.open_discrepancies.length > 0 && (
            <span
              aria-hidden
              className="absolute -top-0.5 -right-0.5 size-1.5 rounded-full bg-status-count ring-1 ring-background"
            />
          )}
        </button>
      </TooltipTrigger>
      <TooltipContent side="top" className="flex-col items-start gap-0.5 py-2">
        <BayPreview bay={bay} />
      </TooltipContent>
    </Tooltip>
  )
}

// The hover card: enough to read a bay without clicking it.
function BayPreview({ bay }: { bay: Bay }) {
  const { pick } = bay
  const status: PickStatus = pick.status
  return (
    <>
      <span className="font-medium">{pick.location}</span>
      <span className="opacity-80">{pick.description ?? 'No SKU slotted'}</span>
      <span className="opacity-80">
        {STATUS_STYLES[status].label}
        {pick.sku_code && ` · ${pick.on_hand} of max ${pick.max_qty} (min ${pick.min_qty})`}
      </span>
      {pick.open_task_id && <span className="opacity-80">Task #{pick.open_task_id} open</span>}
    </>
  )
}
