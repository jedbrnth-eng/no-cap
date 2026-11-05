// Hook stubs with a tiny per-test state slot, enough to call a function component once and read its tree.
export const hookState = { values: [], i: 0, effects: [] }
export function resetHooks(values = []) {
  hookState.values = values
  hookState.i = 0
  hookState.effects = []
}
export function useState(initial) {
  const i = hookState.i++
  if (!(i in hookState.values)) hookState.values[i] = typeof initial === 'function' ? initial() : initial
  return [hookState.values[i], v => { hookState.values[i] = typeof v === 'function' ? v(hookState.values[i]) : v }]
}
export function useEffect(fn) {
  hookState.effects.push(fn)
}
export function useMemo(fn) {
  return fn()
}
export function useCallback(fn) {
  return fn
}
export default { useState, useEffect, useMemo, useCallback }
