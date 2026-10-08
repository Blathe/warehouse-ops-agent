import type { PickStatus } from '@/lib/api'

// Colors and labels for pick face statuses, shared by the map and the details panel.
export const STATUS_STYLES: Record<PickStatus, { label: string; cell: string }> = {
  empty: { label: 'Empty', cell: 'bg-status-empty' },
  low: { label: 'At or below min', cell: 'bg-status-low' },
  ok: { label: 'OK', cell: 'bg-status-ok' },
  unassigned: { label: 'No SKU slotted', cell: 'bg-muted' },
}

export const ZONE_NAMES: Record<string, string> = {
  A: 'Zone A: small tackle',
  B: 'Zone B: rods & reels',
  C: 'Zone C: bulky gear',
}
