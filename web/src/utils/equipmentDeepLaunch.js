/**
 * Carries a card launcher's full context across a host-router navigation.
 *
 * Embedded in the platform shell, pressing 定向深研 on a capability card does
 * two things at once: it dispatches the complete card context, and it asks the
 * host router to switch to the deep-research route.  That route change makes
 * the workbench re-dispatch an open request that only knows the card binding
 * id, which overwrites the card payload and leaves the reader on a blank,
 * unconfigured conversation.  Parking the first context here lets the second
 * dispatch restore what the launcher already resolved.
 */
const LIMIT = 12;
const contexts = new Map();
const text = value => String(value ?? '').trim();
const ownerScope = () => text(globalThis.__EQUIPMENT_USER_ID__) || 'standalone';
const scopedKey = key => `${ownerScope()}\u0000${key}`;

const keysFor = source => [
  text(source?.card_binding_id || source?.cardBindingId),
  text(source?.target_identity || source?.targetIdentity),
  text(source?.capability_id || source?.capabilityId),
].filter(Boolean);

export function rememberDeepLaunchContext(context) {
  const keys = keysFor(context);
  if (!keys.length) return context;
  for (const key of keys) {
    const storageKey = scopedKey(key);
    contexts.delete(storageKey);
    contexts.set(storageKey, context);
  }
  const prefix = `${ownerScope()}\u0000`;
  const ownedKeys = [...contexts.keys()].filter(key => key.startsWith(prefix));
  while (ownedKeys.length > LIMIT) contexts.delete(ownedKeys.shift());
  return context;
}

export function recallDeepLaunchContext(hints = {}) {
  for (const key of keysFor(hints)) {
    const found = contexts.get(scopedKey(key));
    if (found) return found;
  }
  // A target identity is namespaced by kind (`capability-followup:card_binding_id:x`).
  // Fall back to its trailing value so a restored URL still finds the payload.
  const identity = text(hints?.target_identity || hints?.targetIdentity);
  const tail = identity.slice(identity.lastIndexOf(':') + 1);
  return (tail && contexts.get(scopedKey(tail))) || null;
}

export function forgetDeepLaunchContexts() {
  const prefix = `${ownerScope()}\u0000`;
  for (const key of contexts.keys()) {
    if (key.startsWith(prefix)) contexts.delete(key);
  }
}

/**
 * Hand the clicked card to the platform shell.
 *
 * The shell owns the deep-research route and builds its own session there, but
 * its capability table is a different store from the workbench's run
 * artifacts, so looking the card up again by id can miss.  The workbench
 * already holds the row, so publish it instead of making the shell re-resolve
 * it.  sessionStorage is used deliberately: it survives the route change and a
 * reload, and it is scoped to the tab.
 */
const CARD_HANDOFF_KEY = 'equipment:deep-launch-card';
const cardHandoffKey = () => `${CARD_HANDOFF_KEY}:${ownerScope()}`;

export function publishDeepLaunchCard(card) {
  try {
    globalThis.sessionStorage?.setItem(cardHandoffKey(), JSON.stringify(card));
    // Discard the pre-multi-user key so an old tab cannot expose its payload
    // after a different account signs in.
    globalThis.sessionStorage?.removeItem(CARD_HANDOFF_KEY);
  } catch {
    // A private-mode or quota failure only costs the shell its shortcut.
  }
}

export function readDeepLaunchCard(cardKey) {
  try {
    const raw = globalThis.sessionStorage?.getItem(cardHandoffKey());
    const card = raw ? JSON.parse(raw) : null;
    if (!card) return null;
    return !cardKey || text(card.card_key) === text(cardKey) ? card : null;
  } catch {
    return null;
  }
}
