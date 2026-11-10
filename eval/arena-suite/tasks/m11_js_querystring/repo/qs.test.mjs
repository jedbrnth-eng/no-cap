import test from 'node:test';
import assert from 'node:assert/strict';
import { parseQuery } from './qs.mjs';

test('decodes percent', () => {
  assert.deepEqual(parseQuery('q=hello%20world'), { q: 'hello world' });
});
