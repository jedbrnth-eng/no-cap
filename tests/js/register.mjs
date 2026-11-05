// Resolve the three specifiers the Desktop loader allows to local stubs, so desktop/plugin.js runs under `node --test`
// unmodified. Nothing else resolves here either: same rule as the real loader.
import { registerHooks } from 'node:module'

const STUBS = {
  '@hermes/plugin-sdk': new URL('./stubs/sdk.mjs', import.meta.url).href,
  react: new URL('./stubs/react.mjs', import.meta.url).href,
  'react/jsx-runtime': new URL('./stubs/jsx-runtime.mjs', import.meta.url).href
}

registerHooks({
  resolve(specifier, context, next) {
    if (specifier in STUBS) return { url: STUBS[specifier], shortCircuit: true }
    return next(specifier, context)
  }
})
