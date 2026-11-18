import assert from 'node:assert/strict';
import test from 'node:test';
import { clock, middle, took } from '../src/components/agent/format.ts';
import { toolOf } from '../src/components/agent/tools.ts';

test('a time taken is said the short way, and nothing for a time not known', () => {
  assert.equal(took(0.4), '<1s');
  assert.equal(took(12.4), '12s');
  assert.equal(took(248), '4m 08s');
  assert.equal(took(240), '4m');
  assert.equal(took(3725), '1h 02m');
  assert.equal(took(7200), '2h');
  for (const unknown of [null, undefined, -3, Number.NaN, Infinity]) assert.equal(took(unknown), '');
});

test('a running clock reads like a clock', () => {
  assert.equal(clock(7.9), '0:07');
  assert.equal(clock(587), '9:47');
  assert.equal(clock(3725), '1:02:05');
  assert.equal(clock(-4), '0:00');
});

test('a long path keeps its end, where the file is named', () => {
  assert.equal(middle('pictures/a.html'), 'pictures/a.html');
  const cut = middle('house/episodes/ep_0a1b2c3d4e5f/pictures/pic-c2-b2-f1.stills/2.png', 40);
  assert.equal(cut.length, 40);
  assert.ok(cut.endsWith('c2-b2-f1.stills/2.png') && cut.startsWith('house/ep') && cut.includes('…'));
});

test("a step's words say which kind of tool it was and what it touched", () => {
  assert.deepEqual(toolOf('Reading pictures/pic-c2-b2-f1.html'), { kind: 'read', verb: 'Reading', target: 'pictures/pic-c2-b2-f1.html' });
  assert.deepEqual(toolOf('Searching for “"theme"|"layout"” in plan.json'), {
    kind: 'search',
    verb: 'Searching for',
    target: '“"theme"|"layout"” in plan.json',
  });
  // the web's search is never taken for a search of files, and a page read is the web's
  assert.equal(toolOf('Searching the web for “retry with backoff”').kind, 'web');
  assert.equal(toolOf('Reading https://example.com/spec').kind, 'web');
  assert.equal(toolOf('Writing plan.json').kind, 'write');
  assert.equal(toolOf('Editing pictures/pic.html').kind, 'edit');
  assert.equal(toolOf('Listing pictures/*.png').kind, 'list');
  assert.equal(toolOf('Running hyperframes check .').kind, 'run');
  assert.deepEqual(toolOf('Asking a helper: read the brief'), { kind: 'helper', verb: 'Asking a helper', target: 'read the brief' });
  assert.equal(toolOf('Planning its steps').kind, 'plan');
  // anything else is said as it came
  assert.deepEqual(toolOf('mcp__weird_tool'), { kind: 'other', verb: 'mcp__weird_tool', target: '' });
});
