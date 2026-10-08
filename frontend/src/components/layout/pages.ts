import {
  ClipboardCheckIcon,
  LayoutDashboardIcon,
  ListTodoIcon,
  MapIcon,
  MessageSquareIcon,
  ScrollTextIcon,
} from 'lucide-react'

// Every page in the app. The order here is the order in the sidebar.
export const PAGES = [
  { path: '/overview', title: 'Overview', icon: LayoutDashboardIcon },
  { path: '/workspace', title: 'Chat', icon: MessageSquareIcon },
  { path: '/floor-map', title: 'Floor map', icon: MapIcon },
  { path: '/tasks', title: 'Tasks', icon: ListTodoIcon },
  { path: '/counts', title: 'Cycle counts', icon: ClipboardCheckIcon },
  { path: '/agent-log', title: 'Agent log', icon: ScrollTextIcon },
] as const

export type PagePath = (typeof PAGES)[number]['path']
