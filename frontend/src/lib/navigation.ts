/**
 * The tenant sidebar, as data.
 *
 * Which screens a tenant console shows is a function of three things:
 *   - the vertical (what the content panel is called — "Packages", "Services"),
 *   - the tenant's feature flags (a tenant without `human_handover` has no live
 *     inbox), and
 *   - the signed-in admin's permissions (a restricted admin sees fewer items).
 *
 * Keeping it here — rather than hard-coded in `app-shell.tsx` — means a new
 * vertical or capability adds a row, not a branch in the layout.
 */

import {
  AlertTriangle,
  Briefcase,
  Cpu,
  FolderOpen,
  Gift,
  History,
  Inbox,
  KeyRound,
  LayoutGrid,
  ListTree,
  Megaphone,
  MessagesSquare,
  Package,
  ScrollText,
  ShoppingCart,
  Truck,
  Upload,
  Users,
  Phone,
  Calendar,
  type LucideIcon,
} from 'lucide-react'
import type { FeatureFlag, Features } from './types'
import { getVertical } from './verticals'

export interface NavItem {
  /** Route view id: `#/tenants/<tenant>/<id>`. */
  id: string
  label: string
  icon: LucideIcon
  /** Visible when the admin holds any of these. Undefined is ungated. */
  permissions?: string[]
  /** Visible when the tenant has this feature on. Undefined is ungated. */
  feature?: FeatureFlag
  /** True when the sidebar should show the tenant's record count. */
  showsCount?: boolean
}

/**
 * Info pages for the software & IT vertical. Advertised in the navigation —
 * the panel behind each is `InfoPagePanel` (info-page-panel.tsx).
 */
const IT_INFO_ITEMS: NavItem[] = [
  { id: 'projects', label: 'Projects', icon: FolderOpen, permissions: ['manage_projects'] },
  { id: 'technologies', label: 'Technologies', icon: Cpu, permissions: ['manage_technologies'] },
  { id: 'careers', label: 'Careers', icon: Briefcase, permissions: ['manage_careers'] },
  { id: 'benefits', label: 'Benefits', icon: Gift, permissions: ['manage_benefits'] },
]

/**
 * Build the sidebar for one tenant.
 *
 * `features` may be null while the resolved profile is loading (or when the
 * admin lacks `manage_operations`, which that endpoint needs). In that case the
 * feature gate is skipped and only permissions decide — showing a live inbox to
 * someone who cannot open it is a smaller sin than hiding every screen until a
 * request the user may not be allowed to make resolves.
 */
export function buildTenantNav(opts: {
  vertical?: string | null
  features?: Features | null
  can: (permission: string) => boolean
}): NavItem[] {
  const content = getVertical(opts.vertical).content
  const features = opts.features ?? null

  const items: NavItem[] = [
    { id: 'overview', label: 'Overview', icon: LayoutGrid },
    {
      id: 'records',
      label: content.label,
      icon: Package,
      permissions: ['view_products'],
      feature: 'offerings',
      showsCount: true,
    },
    ...(opts.vertical === 'it_software' ? IT_INFO_ITEMS : []),
    {
      id: 'orders',
      label: 'Orders',
      icon: ShoppingCart,
      permissions: ['view_orders'],
      feature: 'orders',
    },
    { id: 'customers', label: 'Customers', icon: Users, permissions: ['view_customers'] },
    { id: 'profile', label: 'Profile', icon: ScrollText, permissions: ['manage_operations'] },
    { id: 'menu', label: 'Menu', icon: ListTree },
    {
      id: 'uploads',
      label: 'Uploads',
      icon: Upload,
      permissions: ['upload_faq', 'upload_kb', 'view_files', 'catalogue_new_arrival'],
    },
    { id: 'campaigns', label: 'Campaigns', icon: Megaphone, permissions: ['view_campaigns'] },
    { id: 'distributors', label: 'Distributors', icon: Truck, permissions: ['view_distributors'] },
    {
      id: 'chat',
      label: 'Admin chat',
      icon: MessagesSquare,
      permissions: ['chat'],
    },
    {
      id: 'chat-history',
      label: 'Chat history',
      icon: History,
      permissions: ['chat_history'],
    },
    {
      id: 'inbox',
      label: 'Live inbox',
      icon: Inbox,
      permissions: ['view_inbox'],
      feature: 'human_handover',
    },
    {
      id: 'complaints',
      label: 'Complaints',
      icon: AlertTriangle,
      permissions: ['view_complaints'],
      feature: 'complaints',
    },
    {
      id: 'callbacks',
      label: 'Callbacks',
      icon: Phone,
      permissions: ['manage_operations'],
      feature: 'callback',
      showsCount: true,
    },
    { id: 'tokens', label: 'API tokens', icon: KeyRound, permissions: ['manage_operations'] },
  ]
  return items.filter((item) => isVisible(item, opts.can, features))
}

/** Whether one item passes its permission and feature gates. */
export function isVisible(
  item: NavItem,
  can: (permission: string) => boolean,
  features: Features | null,
): boolean {
  if (item.permissions && !item.permissions.some((p) => can(p))) return false
  if (item.feature && features && features[item.feature] === false) return false
  return true
}

/** The ids a known view can resolve to — used to decide "unknown view". */
export function knownViews(vertical?: string | null): string[] {
  return buildTenantNav({ vertical, features: null, can: () => true }).map((i) => i.id)
}
