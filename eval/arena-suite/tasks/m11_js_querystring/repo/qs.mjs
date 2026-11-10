export function parseQuery(s) {
  const out = {};
  for (const pair of s.split('&')) {
    if (!pair) continue;
    const [k, v = ''] = pair.split('=');
    out[k] = v;
  }
  return out;
}
