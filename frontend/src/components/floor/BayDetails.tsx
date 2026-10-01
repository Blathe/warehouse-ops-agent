import { STATUS_STYLES } from '@/components/floor/status'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import type { Bay } from '@/lib/api'
import { cn } from '@/lib/utils'

// The stock in one bay: the pick face and the reserve pallets above it.
export function BayDetails({ bay }: { bay: Bay }) {
  const { pick } = bay
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {pick.location}
          <span className={cn('size-3 rounded-sm', STATUS_STYLES[pick.status].cell)} />
        </CardTitle>
        <CardDescription>
          {pick.description ?? 'No SKU slotted in this pick face'}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4 text-sm">
        {pick.sku_code && (
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
            <dt className="text-muted-foreground">SKU</dt>
            <dd className="font-medium">{pick.sku_code}</dd>
            <dt className="text-muted-foreground">On hand</dt>
            <dd className="font-medium">
              {pick.on_hand} (min {pick.min_qty}, max {pick.max_qty})
            </dd>
            <dt className="text-muted-foreground">Status</dt>
            <dd>{STATUS_STYLES[pick.status].label}</dd>
          </dl>
        )}
        {pick.open_task_id && (
          <Badge variant="secondary" className="self-start">
            Replenishment task #{pick.open_task_id} open
          </Badge>
        )}
        <div className="flex flex-col gap-1.5">
          <h4 className="text-xs font-medium text-muted-foreground">Reserve above</h4>
          <ul className="flex flex-col gap-1">
            {[...bay.reserve].reverse().map((slot) => (
              <li key={slot.location} className="flex justify-between gap-2">
                <span className="whitespace-nowrap">{slot.location}</span>
                <span className="text-right text-muted-foreground">
                  {slot.lpn ? `${slot.qty} × SKU ${slot.sku_code} (${slot.lpn})` : 'Empty'}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </CardContent>
    </Card>
  )
}
