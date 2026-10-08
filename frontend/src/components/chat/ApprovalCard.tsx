import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import type { PendingAction } from '@/lib/api'

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
    </dl>
  )
}
