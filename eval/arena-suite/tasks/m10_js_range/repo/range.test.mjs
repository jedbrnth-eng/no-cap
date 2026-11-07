import test from 'node:test';
import assert from 'node:assert/strict';
import { range } from './range.mjs';

test('negative step', () => {
  assert.deepEqual(range(5, 0, -2), [5, 3, 1]);
});
