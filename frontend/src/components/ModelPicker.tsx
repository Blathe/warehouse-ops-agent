import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select'
import type { ModelOption } from '@/lib/api'

interface ModelPickerProps {
  models: ModelOption[]
  value: string
  onChange: (model: string) => void
}

// Picks the Claude model for the next message. Prices are per million tokens, so the
// cheaper tiers are easy to spot.
export function ModelPicker({ models, value, onChange }: ModelPickerProps) {
  return (
    <NativeSelect
      aria-label="Model"
      size="sm"
      value={value}
      onChange={(event) => onChange(event.target.value)}
    >
      {models.map((model) => (
        <NativeSelectOption key={model.id} value={model.id}>
          {model.label} ({usd(model.input_per_mtok)} / {usd(model.output_per_mtok)} per M tokens)
        </NativeSelectOption>
      ))}
    </NativeSelect>
  )
}

// Whole dollars stay short ($4); fractions show cents ($0.10, not $0.1).
function usd(amount: number): string {
  return Number.isInteger(amount) ? `$${amount}` : `$${amount.toFixed(2)}`
}
