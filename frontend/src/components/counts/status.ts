import type { CountFilter, CountStatus } from '@/lib/api'

// Labels and colors for cycle count statuses. Orange for open matches the map marker.
export const COUNT_STATUS: Record<CountStatus, { label: string; badge: string }> = {
  DISCREPANCY: {
    label: 'Discrepancy',
    badge: 'bg-status-count-soft text-status-count-ink',
  },
  RECOUNT_REQUESTED: {
    label: 'Recount requested',
    badge: 'bg-status-low-soft text-status-low-ink',
  },
  ACCEPTED: {
    label: 'Accepted',
    badge: 'bg-status-ok-soft text-status-ok-ink',
  },
  RECOUNTED: { label: 'Recounted', badge: 'bg-muted text-muted-foreground' },
  MATCHED: { label: 'Matched', badge: 'bg-muted text-muted-foreground' },
}

export const COUNT_FILTERS: { value: CountFilter; label: string }[] = [
  { value: 'open', label: 'Open' },
  { value: 'resolved', label: 'Resolved' },
  { value: 'all', label: 'All' },
]

// +12 / −12, with a real minus sign.
export function formatVariance(variance: number): string {
  return variance > 0 ? `+${variance}` : `−${Math.abs(variance)}`
}
