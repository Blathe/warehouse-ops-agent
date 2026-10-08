import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { getFloorMap, type Bay, type PendingAction } from '@/lib/api'
import { cn } from '@/lib/utils'

interface ApprovalCardProps {
  actions: PendingAction[]
  busy: boolean
  onDecide: (approve: boolean) => void
}

// Shown when the agent wants to create replenishment tasks. Nothing is written
// until someone clicks Approve.
export function ApprovalCard({ actions, busy, onDecide }: ApprovalCardProps) {
  return (
    <Card className="w-full max-w-md border-status-low/50 bg-status-low-soft/60">
      <CardHeader>
        <CardTitle>Approve replenishment?</CardTitle>
        <CardDescription>
          {actions.length === 1
            ? 'The agent wants to create this task.'
            : `The agent wants to create these ${actions.length} tasks.`}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {actions.map((action) => (
          <ActionDetails key={action.tool_use_id} action={action} />
        ))}
      </CardContent>
      <CardFooter className="gap-2">
        <Button disabled={busy} onClick={() => onDecide(true)}>
          Approve
        </Button>
        <Button variant="outline" disabled={busy} onClick={() => onDecide(false)}>
          Reject
        </Button>
      </CardFooter>
    </Card>
  )
}

function ActionDetails({ action }: { action: PendingAction }) {
  const input = action.input
  if (action.tool !== 'create_replenishment_task') {
    return <pre className="text-xs">{JSON.stringify(input, null, 2)}</pre>
  }
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
      <dt className="text-muted-foreground">SKU</dt>
      <dd className="font-medium">{String(input.sku_code)}</dd>
      <dt className="text-muted-foreground">Move</dt>
      <dd className="font-medium">
        {String(input.qty)} from {String(input.from_location)} to {String(input.to_location)}
      </dd>
      <dt className="text-muted-foreground">Reason</dt>
      <dd>{String(input.reason)}</dd>
      <dd className="col-span-2 mt-1">
        <MoveImpact
          from={String(input.from_location)}
          to={String(input.to_location)}
          qty={Number(input.qty)}
        />
      </dd>
    </dl>
  )
}

// What the move does to the stock: the pick face fills up and the reserve pallet shrinks.
// The numbers come from the floor map; if they can't be loaded the card simply omits this.
function MoveImpact({ from, to, qty }: { from: string; to: string; qty: number }) {
  const [bays, setBays] = useState<Bay[] | null>(null)

  useEffect(() => {
    getFloorMap()
      .then((map) => setBays(map.bays))
      .catch(() => setBays(null))
  }, [])

  const face = bays?.find((b) => b.pick.location === to)?.pick
  const pallet = bays?.flatMap((b) => b.reserve).find((r) => r.location === from)
  if (!face || !pallet || face.max_qty === null) return null

  return (
    <div className="flex flex-col gap-2 rounded-lg border bg-background/60 p-3">
      <StockChange
        label={`Pick face ${to}`}
        before={face.on_hand}
        after={face.on_hand + qty}
        scale={face.max_qty}
        tone="bg-status-ok"
      />
      <StockChange
        label={`Reserve ${from}`}
        before={pallet.qty}
        after={pallet.qty - qty}
        scale={pallet.qty}
        tone="bg-status-task"
      />
    </div>
  )
}

// A bar showing the stock before the move, with the part that changes shaded: added stock in
// the colour, removed stock as a faded stripe.
function StockChange({
  label,
  before,
  after,
  scale,
  tone,
}: {
  label: string
  before: number
  after: number
  scale: number
  tone: string
}) {
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-medium tabular-nums">
          {before} → {after}
        </span>
      </div>
      <div
        role="img"
        aria-label={`${label}: ${before} before, ${after} after`}
        className="relative flex h-2 overflow-hidden rounded-full bg-muted"
      >
        <div
          className={cn('h-full', tone)}
          style={{ width: `${(Math.min(before, after) / scale) * 100}%` }}
        />
        <div
          className={cn('h-full', after > before ? tone : 'bg-foreground/15', after > before && 'opacity-50')}
          style={{ width: `${(Math.abs(after - before) / scale) * 100}%` }}
        />
      </div>
    </div>
  )
}
