import { ArrowUpIcon, BotIcon, CheckIcon, SquarePenIcon, XIcon } from 'lucide-react'
import { useState, type FormEvent, type KeyboardEvent } from 'react'

import { describeRunning } from '@/components/activity/activity'
import { formatCost } from '@/components/agentlog/format'
import { ApprovalCard } from '@/components/chat/ApprovalCard'
import { Markdown } from '@/components/chat/Markdown'
import { ToolCalls } from '@/components/chat/ToolCalls'
import { Bubble, BubbleContent } from '@/components/ui/bubble'
import { Button } from '@/components/ui/button'
import { Message, MessageAvatar, MessageContent, MessageFooter } from '@/components/ui/message'
import {
  MessageScroller,
  MessageScrollerButton,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerProvider,
  MessageScrollerViewport,
} from '@/components/ui/message-scroller'
import { Spinner } from '@/components/ui/spinner'
import { Textarea } from '@/components/ui/textarea'
import {
  getSessionSteps,
  streamApproval,
  streamChat,
  type AgentStep,
  type AgentTurn,
  type PendingAction,
  type ToolTrace,
} from '@/lib/api'

interface Entry {
  id: number
  role: 'user' | 'assistant' | 'error'
  text: string
  toolCalls: ToolTrace[]
  pending: PendingAction[] // non-empty while waiting for Approve / Reject
  decision?: string // e.g. "Approved by Pat", shown once decided
  model?: string // which model wrote an assistant reply
}

interface ChatProps {
  supervisor: string
  model: string | null // null = let the backend use its default
  modelLabels?: Record<string, string>
  onTurn?: (turn: AgentTurn) => void // after every agent response, e.g. to refresh the map
}

const SUGGESTIONS = [
  'What needs replenishing?',
  'Any short picks in zone A in the last 24 hours?',
  'Refill the empty pick faces in zone B.',
]

// One line in the live progress list while the agent works.
interface StepLine {
  id: number
  label: string
  state: 'running' | 'done' | 'failed'
}

let nextId = 1

export function Chat({ supervisor, model, modelLabels = {}, onTurn }: ChatProps) {
  // useState is React's per-component state: calling the setter re-renders the
  // component with the new value (roughly a ViewModel property that raises PropertyChanged).
  const [entries, setEntries] = useState<Entry[]>([])
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [steps, setSteps] = useState<StepLine[]>([]) // what the agent is doing right now
  const [cost, setCost] = useState<number | null>(null) // USD spent on this conversation so far

  const awaitingApproval = entries.some((e) => e.pending.length > 0)

  function add(entry: Omit<Entry, 'id'>) {
    setEntries((current) => [...current, { ...entry, id: nextId++ }])
  }

  function addTurn(turn: AgentTurn) {
    setConversationId(turn.conversation_id)
    add({
      role: 'assistant',
      text: turn.reply,
      toolCalls: turn.tool_calls,
      pending: turn.pending,
      model: modelLabels[turn.model] ?? turn.model,
    })
    onTurn?.(turn)
    // Cost is logged per Claude request in the Agent log; add up this conversation's requests.
    getSessionSteps(turn.conversation_id)
      .then((steps) => setCost(steps.reduce((sum, s) => sum + (s.model_call?.cost_usd ?? 0), 0)))
      .catch(() => {
        // The strip just keeps its last figure.
      })
  }

  function newChat() {
    setEntries([])
    setConversationId(null)
    setDraft('')
    setCost(null)
  }

  // Folds one streamed event into the progress list: a tool starting adds a running line, its
  // end marks the last matching running line done or failed. "thinking" needs no line of its
  // own, since the list always ends with a "Thinking..." marker while busy.
  function onStep(step: AgentStep) {
    if (step.type === 'tool_start' && step.tool) {
      const label = describeRunning(step.tool, step.input ?? {})
      setSteps((current) => [...current, { id: nextId++, label, state: 'running' }])
    } else if (step.type === 'tool_end') {
      setSteps((current) => {
        const index = current.findLastIndex((line) => line.state === 'running')
        if (index === -1) return current
        return current.map((line, i) =>
          i === index ? { ...line, state: step.ok ? 'done' : 'failed' } : line,
        )
      })
    }
  }

  async function run(request: (onStep: (step: AgentStep) => void) => Promise<AgentTurn>) {
    setBusy(true)
    setSteps([])
    try {
      addTurn(await request(onStep))
    } catch (error) {
      add({ role: 'error', text: (error as Error).message, toolCalls: [], pending: [] })
    } finally {
      setBusy(false)
    }
  }

  function send(text: string) {
    const message = text.trim()
    if (!message || busy || awaitingApproval) return
    add({ role: 'user', text: message, toolCalls: [], pending: [] })
    setDraft('')
    void run((onStep) => streamChat(message, conversationId, model, onStep))
  }

  function decide(approve: boolean) {
    if (!conversationId) return
    const decision = `${approve ? 'Approved' : 'Rejected'} by ${supervisor}`
    setEntries((current) =>
      current.map((e) => (e.pending.length ? { ...e, pending: [], decision } : e)),
    )
    void run((onStep) => streamApproval(conversationId, approve, supervisor, onStep))
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    send(draft)
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      send(draft)
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex h-11 shrink-0 items-center gap-3 border-b px-4 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <BotIcon className="size-3.5" aria-hidden />
          {model ? (modelLabels[model] ?? model) : 'Default model'}
        </span>
        {cost !== null && (
          <span className="tabular-nums" aria-label={`Cost of this chat: ${formatCost(cost)}`}>
            {formatCost(cost)} this chat
          </span>
        )}
        <Button
          variant="ghost"
          size="xs"
          className="ml-auto"
          disabled={entries.length === 0 || busy}
          onClick={newChat}
        >
          <SquarePenIcon />
          New chat
        </Button>
      </div>
      <MessageScrollerProvider>
        <MessageScroller>
          <MessageScrollerViewport>
            <MessageScrollerContent className="mx-auto w-full max-w-3xl p-4">
              {entries.length === 0 && <EmptyState onPick={send} />}
              {entries.map((entry) => (
                <MessageScrollerItem key={entry.id} scrollAnchor={entry.role === 'user'}>
                  <EntryView entry={entry} busy={busy} supervisor={supervisor} onDecide={decide} />
                </MessageScrollerItem>
              ))}
              {busy && (
                <MessageScrollerItem>
                  <ul aria-label="Agent progress" aria-live="polite" className="flex flex-col gap-1.5">
                    {steps.map((line) => (
                      <li
                        key={line.id}
                        className="flex items-center gap-2 text-sm text-muted-foreground"
                      >
                        {line.state === 'running' ? (
                          <Spinner className="size-4" />
                        ) : line.state === 'done' ? (
                          <CheckIcon aria-label="done" className="size-4 text-status-ok-ink" />
                        ) : (
                          <XIcon aria-label="failed" className="size-4 text-status-empty-ink" />
                        )}
                        {line.label}
                      </li>
                    ))}
                    {steps.every((line) => line.state !== 'running') && (
                      <li className="flex items-center gap-2 text-sm text-muted-foreground">
                        <Spinner className="size-4" />
                        Thinking...
                      </li>
                    )}
                  </ul>
                </MessageScrollerItem>
              )}
            </MessageScrollerContent>
          </MessageScrollerViewport>
          <MessageScrollerButton />
        </MessageScroller>
      </MessageScrollerProvider>

      <form onSubmit={onSubmit} className="mx-auto flex w-full max-w-3xl items-end gap-2 p-4">
        <Textarea
          aria-label="Message"
          placeholder={
            awaitingApproval ? 'Approve or reject the task first' : 'Ask about short picks or stock...'
          }
          value={draft}
          disabled={awaitingApproval}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={onKeyDown}
          className="max-h-40 min-h-10 resize-none"
        />
        <Button
          type="submit"
          size="icon"
          aria-label="Send"
          disabled={busy || awaitingApproval || !draft.trim()}
        >
          <ArrowUpIcon />
        </Button>
      </form>
    </div>
  )
}

function EntryView({
  entry,
  busy,
  supervisor,
  onDecide,
}: {
  entry: Entry
  busy: boolean
  supervisor: string
  onDecide: (approve: boolean) => void
}) {
  const align = entry.role === 'user' ? 'end' : 'start'
  const variant = entry.role === 'user' ? 'default' : entry.role === 'error' ? 'destructive' : 'muted'
  return (
    <Message align={align}>
      {entry.role !== 'error' && (
        <MessageAvatar className="size-7 min-w-7 self-start">
          {entry.role === 'user' ? (
            <span aria-hidden className="text-xs font-medium">
              {supervisor.charAt(0).toUpperCase()}
            </span>
          ) : (
            <BotIcon aria-hidden className="size-4 text-primary" />
          )}
        </MessageAvatar>
      )}
      <MessageContent>
        {entry.text && (
          // Replies are markdown (the model writes tables and lists) and get the full width;
          // what the supervisor typed and error messages stay plain text.
          <Bubble variant={variant} className={entry.role === 'assistant' ? 'max-w-full' : undefined}>
            {entry.role === 'assistant' ? (
              <BubbleContent>
                <Markdown>{entry.text}</Markdown>
              </BubbleContent>
            ) : (
              <BubbleContent className="whitespace-pre-wrap">{entry.text}</BubbleContent>
            )}
          </Bubble>
        )}
        {entry.pending.length > 0 && (
          <ApprovalCard actions={entry.pending} busy={busy} onDecide={onDecide} />
        )}
        <ToolCalls calls={entry.toolCalls} />
        {(entry.decision || entry.model) && (
          <MessageFooter className="px-0">
            {[entry.model, entry.decision].filter(Boolean).join(' · ')}
          </MessageFooter>
        )}
      </MessageContent>
    </Message>
  )
}

function EmptyState({ onPick }: { onPick: (text: string) => void }) {
  return (
    <div className="flex flex-col items-center gap-3 py-16 text-center">
      <p className="text-sm text-muted-foreground">
        Ask about short picks, stock locations or which pick faces need refilling.
      </p>
      <div className="flex flex-wrap justify-center gap-2">
        {SUGGESTIONS.map((text) => (
          <Button key={text} variant="outline" size="sm" onClick={() => onPick(text)}>
            {text}
          </Button>
        ))}
      </div>
    </div>
  )
}
