import assert from 'node:assert/strict'

// Existing database users only. This helper never creates or changes an account.
export function accountFor(role) {
  const key = `PLATFORM_TEST_${role.toUpperCase()}_USERNAME`
  const username = process.env[key]
  assert(username, `Set ${key} to an existing database user's login name.`)
  return username
}
