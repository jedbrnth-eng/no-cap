import test from 'node:test';
import assert from 'node:assert/strict';
import { range } from '../range.mjs';

test('negative step', () => {
  assert.deepEqual(range(5, 0, -2), [5, 3, 1]);
  assert.deepEqual(range(3, -1, -1), [3, 2, 1, 0]);
});

test('positive and default', () => {
  assert.deepEqual(range(0, 3), [0, 1, 2]);
  assert.deepEqual(range(1, 10, 4), [1, 5, 9]);
  assert.deepEqual(range(3, 3), []);
});

test('zero step throws', () => {
  assert.throws(() => range(0, 5, 0), RangeError);
});
