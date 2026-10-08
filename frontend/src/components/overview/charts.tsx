import { ZONE_NAMES } from '@/components/floor/status'
import type { OverviewData, PickStatus, ZoneHealth } from '@/lib/api'
import { cn } from '@/lib/utils'

// The charts are plain divs sized with percentages: two simple charts don't need a charting
// library. (In .NET terms, a styled ProgressBar rather than a full charting control.)

const SEGMENTS: { status: Exclude<PickStatus, 'unassigned'>; label: string; color: string }[] = [
  { status: 'empty', label: 'Empty', color: 'bg-status-empty' },
  { status: 'low', label: 'At or below min', color: 'bg-status-low' },
  { status: 'ok', label: 'OK', color: 'bg-status-ok' },
]

// One stacked bar per zone: how many of its stocked pick faces are empty, low or fine.
export function ZoneHealthChart({ zones }: { zones: ZoneHealth[] }) {
  return (
    <div className="flex flex-col gap-4">
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground" aria-label="Legend">
        {SEGMENTS.map((s) => (
          <li key={s.status} className="flex items-center gap-1.5">
            <span className={cn('size-2.5 rounded-sm', s.color)} />
            {s.label}
          </li>
        ))}
      </ul>
      {zones.map((zone) => {
        const stocked = zone.ok + zone.low + zone.empty
        const attention = zone.low + zone.empty
        return (
          <div key={zone.zone} className="flex flex-col gap-1.5">
            <div className="flex items-baseline justify-between gap-2 text-sm">
              <span className="font-medium">{ZONE_NAMES[zone.zone] ?? `Zone ${zone.zone}`}</span>
              <span className="text-xs text-muted-foreground tabular-nums">
                {attention} of {stocked} need refilling
              </span>
            </div>
            <div
              role="img"
              aria-label={`Zone ${zone.zone}: ${zone.empty} empty, ${zone.low} low, ${zone.ok} ok`}
              className="flex h-3 overflow-hidden rounded-full bg-muted"
            >
              {SEGMENTS.map((s) => (
                <div
                  key={s.status}
                  className={cn(s.color, 'transition-[width] duration-500')}
                  style={{ width: `${stocked ? (zone[s.status] / stocked) * 100 : 0}%` }}
                />
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function hourLabel(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: 'numeric' })
}

// One bar per hour for the last day, tallest bar = the busiest hour.
export function ShortPicksChart({ buckets }: { buckets: OverviewData['short_picks_by_hour'] }) {
  const max = Math.max(1, ...buckets.map((b) => b.short_picks))
  const total = buckets.reduce((sum, b) => sum + b.short_picks, 0)
  return (
    <div className="flex flex-col gap-2">
      <div
        role="img"
        aria-label={`${total} short picks in the last 24 hours, by hour`}
        className="flex h-32 items-end gap-0.5"
      >
        {buckets.map((b) => (
          <div
            key={b.hour_start}
            title={`${hourLabel(b.hour_start)}: ${b.short_picks} short ${b.short_picks === 1 ? 'pick' : 'picks'}`}
            className="flex h-full flex-1 items-end"
          >
            <div
              className={cn(
                'w-full rounded-t-sm transition-[height] duration-500',
                b.short_picks ? 'bg-primary' : 'bg-muted',
              )}
              style={{ height: b.short_picks ? `${(b.short_picks / max) * 100}%` : '2px' }}
            />
          </div>
        ))}
      </div>
      <div className="flex justify-between text-[11px] text-muted-foreground" aria-hidden>
        {[0, 6, 12, 18, buckets.length - 1].map((i) => (
          <span key={i}>{buckets[i] ? hourLabel(buckets[i].hour_start) : ''}</span>
        ))}
      </div>
    </div>
  )
}
