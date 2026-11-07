import test from 'node:test';
import assert from 'node:assert/strict';
import { chunk } from '../chunk.mjs';

test('keeps partial chunk', () => {
  assert.deepEqual(chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]]);
});
