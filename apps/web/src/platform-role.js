export const GLOBAL_BUSINESS_ROLES = new Set(['admin', 'superadmin']);

export function isGlobalBusinessRole(role) {
  return GLOBAL_BUSINESS_ROLES.has(String(role || '').trim());
}
