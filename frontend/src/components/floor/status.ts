import type { PickStatus } from '@/lib/api'

// Colors and labels for pick face statuses, shared by the map and the details panel.
export const STATUS_STYLES: Record<PickStatus, { label: string; cell: string }> = {
  empty: { label: 'Empty', cell: 'bg-red-500' },
  low: { label: 'At or below min', cell: 'bg-amber-400' },
  ok: { label: 'OK', cell: 'bg-emerald-500/70' },
  unassigned: { label: 'No SKU slotted', cell: 'bg-muted' },
}
