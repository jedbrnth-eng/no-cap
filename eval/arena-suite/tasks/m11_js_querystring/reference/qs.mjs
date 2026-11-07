export function parseQuery(s) {
  const out = {};
  if (s.startsWith('?')) s = s.slice(1);
  const dec = x => decodeURIComponent(x.replace(/\+/g, ' '));
  for (const pair of s.split('&')) {
    if (!pair) continue;
    const i = pair.indexOf('=');
    const k = dec(i < 0 ? pair : pair.slice(0, i));
    const v = i < 0 ? '' : dec(pair.slice(i + 1));
    if (k in out) out[k] = [].concat(out[k], v);
    else out[k] = v;
  }
  return out;
}
