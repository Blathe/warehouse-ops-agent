import type { CountFilter, CountStatus } from '@/lib/api'

// Labels and colors for cycle count statuses. Orange for open matches the map marker.
export const COUNT_STATUS: Record<CountStatus, { label: string; badge: string }> = {
  DISCREPANCY: {
    label: 'Discrepancy',
    badge: 'bg-orange-100 text-orange-900 dark:bg-orange-950 dark:text-orange-200',
  },
  RECOUNT_REQUESTED: {
    label: 'Recount requested',
    badge: 'bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200',
  },
  ACCEPTED: {
    label: 'Accepted',
    badge: 'bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200',
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
