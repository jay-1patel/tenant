/**
 * Permissions, mirrored from `ALL_PERMISSIONS` in `backend/routes/auth.py`.
 *
 * Two separate things use this:
 *   - the console decides which screens and buttons a signed-in admin sees, and
 *   - the Team screen renders one switch per permission, grouped for readability.
 *
 * The server re-checks every one of these. Hiding a button is politeness; the
 * authorisation that matters is in `require_permission` / `require_tenant_access`.
 */

import { useAuth } from './auth'

export const PERMISSION_GROUPS: { label: string; permissions: string[] }[] = [
  {
    label: 'Tenant configuration',
    permissions: ['manage_operations'],
  },
  {
    label: 'Team',
    permissions: ['manage_admins'],
  },
  {
    label: 'Content',
    permissions: ['upload_faq', 'upload_kb', 'view_files', 'delete_files'],
  },
  {
    label: 'Products & brochure',
    permissions: [
      'view_products',
      'edit_delete_products',
      'catalogue_new_arrival',
      'view_distributors',
      'manage_distributors',
    ],
  },
  {
    label: 'Conversations',
    permissions: ['chat', 'chat_history', 'view_inbox'],
  },
  {
    label: 'Operations',
    permissions: ['view_orders', 'manage_orders', 'view_complaints', 'manage_complaints', 'view_customers'],
  },
  {
    label: 'Growth',
    permissions: ['view_campaigns', 'manage_campaigns', 'view_analytics'],
  },
]

/**
 * The catalogue + pages an admin manages, per vertical. A shop tenant's team
 * gets add/edit/delete product switches; a software & IT tenant's team gets
 * services and its info pages instead. Unknown or missing verticals fall back
 * to the generic group.
 */
function contentGroupsFor(vertical: string | null | undefined): { label: string; permissions: string[] } {
  if (vertical === 'ecommerce') {
    return {
      label: 'Products & brochure',
      permissions: [
        'view_products',
        'add_product',
        'edit_product',
        'delete_product',
        'catalogue_new_arrival',
        'view_distributors',
        'manage_distributors',
      ],
    }
  }
  if (vertical === 'it_software') {
    return {
      label: 'Services & IT pages',
      permissions: [
        'view_products',
        'manage_services',
        'manage_projects',
        'manage_technologies',
        'manage_careers',
        'manage_benefits',
      ],
    }
  }
  return {
    label: 'Products & brochure',
    permissions: [
      'view_products',
      'edit_delete_products',
      'catalogue_new_arrival',
      'view_distributors',
      'manage_distributors',
    ],
  }
}

/**
 * The permission groups to render for a tenant of a given vertical — the
 * static list, with the catalogue group swapped for the vertical's own.
 */
export function permissionGroups(vertical?: string | null): { label: string; permissions: string[] }[] {
  return PERMISSION_GROUPS.map((group) =>
    group.label === 'Products & brochure' ? contentGroupsFor(vertical) : group,
  )
}

export const PERMISSION_LABELS: Record<string, string> = {
  manage_admins: 'Manage admins',
  upload_faq: 'Upload FAQ files',
  upload_kb: 'Upload KB files',
  view_files: 'View uploaded files',
  delete_files: 'Delete uploaded files',
  view_products: 'View products',
  edit_delete_products: 'Edit/delete products',
  manage_operations: 'Manage operations (profiles, menus, tenants)',
  chat: 'Use admin chat',
  chat_history: 'View chat history',
  catalogue_new_arrival: 'Manage brochure and new releases',
  view_orders: 'View orders',
  manage_orders: 'Edit/delete orders',
  view_complaints: 'View complaints',
  manage_complaints: 'Handle complaints',
  view_customers: 'View customers',
  view_analytics: 'View analytics',
  view_inbox: 'Live inbox',
  view_campaigns: 'Campaigns',
  manage_campaigns: 'Edit/delete campaigns',
  view_distributors: 'Distributors',
  manage_distributors: 'Add/edit/delete distributors',
  add_product: 'Add catalogue entries',
  edit_product: 'Edit catalogue entries',
  delete_product: 'Remove catalogue entries',
  manage_services: 'Add/edit/delete services',
  manage_projects: 'Edit the projects page',
  manage_technologies: 'Edit the technologies page',
  manage_careers: 'Edit the careers page',
  manage_benefits: 'Edit the benefits page',
}

export const ALL_PERMISSIONS = Object.keys(PERMISSION_LABELS)

/** Reading or changing anything tenant-scoped needs manage_operations. */
export const TENANT_PERMISSION = 'manage_operations'
/** The team screen needs manage_admins. */
export const TEAM_PERMISSION = 'manage_admins'

/**
 * Which permissions allow each write action on a tenant's catalogue, mirroring
 * `_require_write_access` in `backend/routes/offerings.py`. `edit_delete_products`
 * remains the all-in-one grant; vertical-specific grants can be finer.
 */
export function contentWritePerms(vertical?: string | null): {
  add: string[]
  edit: string[]
  remove: string[]
} {
  if (vertical === 'it_software') {
    const all = ['edit_delete_products', 'manage_services']
    return { add: all, edit: all, remove: all }
  }
  return {
    add: ['edit_delete_products', 'add_product'],
    edit: ['edit_delete_products', 'edit_product'],
    remove: ['edit_delete_products', 'delete_product'],
  }
}

/**
 * First-login lock: a tenant admin whose tenant has never had a profile
 * published (i.e. whose registration a super admin has not approved yet)
 * is still onboarding. Until the approval lands they only get
 * "Register a tenant" and "My change requests".
 */
export function isOnboardingLocked(
  identity: { role?: string | null; tenant_id?: string | null } | null,
  tenants: { id: string; current_version?: number }[],
): boolean {
  if (!identity || identity.role === 'super_admin' || !identity.tenant_id) return false
  const own = tenants.find((t) => t.id === identity.tenant_id)
  return Boolean(own && !own.current_version)
}

/** The views a locked (onboarding) admin may use. */
export const ONBOARDING_VIEWS = new Set(['register', 'tenant-requests'])

export function usePermissions() {
  const { can, identity } = useAuth()
  return {
    identity,
    isSuperAdmin: identity?.role === 'super_admin',
  isAdmin: identity?.role === 'admin',
  isSubAdmin: identity?.role === 'sub_admin',
  can,
    canManageTenants: can(TENANT_PERMISSION),
    canManageTeam: can(TEAM_PERMISSION),
  }
}
