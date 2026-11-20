import assert from 'node:assert/strict';
import test from 'node:test';
import { middle, plainly, took } from '../src/components/agent/format.ts';
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

test('a long path keeps its end, where the file is named', () => {
  assert.equal(middle('pictures/a.html'), 'pictures/a.html');
  const cut = middle('house/episodes/ep_0a1b2c3d4e5f/pictures/pic-c2-b2-f1.stills/2.png', 40);
  assert.equal(cut.length, 40);
  assert.ok(cut.endsWith('c2-b2-f1.stills/2.png') && cut.startsWith('house/ep') && cut.includes('…'));
});

test("an agent's own words read without their markdown marks, and names keep their underscores", () => {
  assert.equal(plainly('**Decoding is the loop** that `LLM._run_engine()` drives'), 'Decoding is the loop that LLM._run_engine() drives');
  assert.equal(plainly('## Why\nsnake_case and __init__ stay'), 'Why\nsnake_case and __init__ stay');
});

test("a step's words say which kind of tool it was and what it touched", () => {
  assert.deepEqual(toolOf('Reading pictures/pic-c2-b2-f1.html'), { kind: 'read', verb: 'Reading', did: 'Read', target: 'pictures/pic-c2-b2-f1.html' });
  assert.deepEqual(toolOf('Searching for “"theme"|"layout"” in plan.json'), {
    kind: 'search',
    verb: 'Searching for',
    did: 'Searched for',
    target: '“"theme"|"layout"” in plan.json',
  });
  // the web's search is never taken for a search of files, and a page read is the web's
  assert.equal(toolOf('Searching the web for “retry with backoff”').kind, 'web');
  assert.equal(toolOf('Reading https://example.com/spec').kind, 'web');
  assert.equal(toolOf('Writing plan.json').kind, 'write');
  assert.equal(toolOf('Editing pictures/pic.html').kind, 'edit');
  assert.equal(toolOf('Listing pictures/*.png').kind, 'list');
  assert.equal(toolOf('Running hyperframes check .').kind, 'run');
  assert.deepEqual(toolOf('Asking a helper: read the brief'), { kind: 'helper', verb: 'Asking a helper', did: 'Asked a helper', target: 'read the brief' });
  assert.equal(toolOf('Planning its steps').kind, 'plan');
  // anything else is said as it came
  assert.deepEqual(toolOf('mcp__weird_tool'), { kind: 'other', verb: 'mcp__weird_tool', did: 'mcp__weird_tool', target: '' });
  // a step that is done is said as done
  assert.equal(toolOf('Writing plan.json').did, 'Wrote');
  assert.equal(toolOf('Running hyperframes check .').did, 'Ran');
});

test('a turn between two steps is thinking, writing, waiting, quiet or lost by what was last heard', async () => {
  const { nowOf, signalOf, tail, counted, QUIET, LOST_TELLING, LOST_SILENT } = await import('../src/components/agent/signal.ts');
  const pulse = (over) => ({ at: 1000, since: 900, doing: 'thinking', text: 'Which example carries it?', amount: 400, ...over });
  // heard from just now, with nothing known: the newest step says it all
  assert.equal(nowOf(1005, 1000, null, true), null);
  assert.equal(signalOf(null), 'live');
  // thinking and writing are what the agent's own stream says, while it is newer than the last step
  assert.deepEqual(nowOf(1002, 990, pulse(), true), { kind: 'thinking', since: 900, words: 'Which example carries it?', tokens: 400 });
  assert.deepEqual(nowOf(1002, 990, pulse({ doing: 'step', text: 'Writing plan.json', amount: 1200 }), true), { kind: 'writing', since: 900, step: 'Writing plan.json', amount: 1200 });
  assert.deepEqual(nowOf(1002, 990, pulse({ doing: 'writing', text: '', amount: 90 }), true), { kind: 'writing', since: 900, step: '', amount: 90 });
  assert.equal(signalOf(nowOf(1002, 990, pulse(), true)), 'live');
  // a pulse from before the newest step is about what came before it
  assert.equal(nowOf(1012, 1010, pulse(), true), null);
  // silent: an agent that tells is waiting on its model, one that does not is quiet as usual
  assert.deepEqual(nowOf(1000 + QUIET, 1000, null, true), { kind: 'waiting', since: 1000 });
  assert.deepEqual(nowOf(1000 + QUIET, 1000, null, false), { kind: 'quiet', since: 1000 });
  assert.equal(signalOf({ kind: 'quiet', since: 1000 }), 'quiet');
  // silent too long: sooner for an agent that is usually heard from every few seconds
  assert.deepEqual(nowOf(1000 + LOST_TELLING, 990, pulse(), true), { kind: 'lost', since: 1000 });
  assert.equal(nowOf(1000 + LOST_TELLING, 1000, null, false)?.kind, 'quiet');
  assert.deepEqual(nowOf(1000 + LOST_SILENT, 1000, null, false), { kind: 'lost', since: 1000 });
  assert.equal(signalOf({ kind: 'lost', since: 1000 }), 'lost');
  // before a turn has a time to count from, nothing is said
  assert.equal(nowOf(1000, null, pulse(), true), null);
  // a page that has lost the house knows nothing of the agent: no silence is blamed on it
  assert.deepEqual(nowOf(1000 + LOST_SILENT, 1000, pulse(), true, 1500), { kind: 'cut', since: 1500 });
  assert.equal(signalOf({ kind: 'cut', since: 1500 }), 'cut');
  // a thought is shown by its end, from a word's start
  assert.equal(tail('short'), 'short');
  const long = tail('one two three four five six seven eight nine ten eleven twelve', 20);
  assert.ok(long.startsWith('…') && long.endsWith('eleven twelve') && long.length <= 21);
  assert.equal(counted(96400), '96,400');
});
