import { toast } from 'sonner'

import type { ActivityItem } from '@/components/activity/activity'

// Pops a toast for an activity line, coloured by its tone. Used for things that happen while
// the supervisor may be looking at another page: the crew finishing a task, a count finishing.
export function notifyActivity(item: Pick<ActivityItem, 'title' | 'detail' | 'tone'>): void {
  const options = { description: item.detail || undefined }
  switch (item.tone) {
    case 'success':
      toast.success(item.title, options)
      break
    case 'warning':
      toast.warning(item.title, options)
      break
    case 'error':
      toast.error(item.title, options)
      break
    default:
      toast.info(item.title, options)
  }
}
