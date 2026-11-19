import assert from 'node:assert/strict';
import test from 'node:test';
import { beatsOf, beatsSaid } from '../src/episode.ts';

const chapter = (id, beats) => ({ id, beats: beats.map((frames, i) => ({ id: `${id}.b${i + 1}`, frames: frames.map((f) => ({ id: f })) })) });
const view = { plan: { chapters: [chapter('c1', [['c1.b1.f1'], ['c1.b2.f1'], ['c1.b3.f1', 'c1.b3.f2'], ['c1.b4.f1'], ['c1.b5.f1']])] } };

test('a picture names the beats it plays over, as the script numbers them', () => {
  // one picture drawn for four lines of four beats
  const unit = { chapter: 'c1', frames: ['c1.b2.f1', 'c1.b3.f1', 'c1.b3.f2', 'c1.b4.f1', 'c1.b5.f1'] };
  assert.deepEqual(beatsOf(view, unit), [2, 3, 4, 5]);
  assert.equal(beatsSaid(beatsOf(view, unit)), 'Beats 2–5');
  // one line of its own
  assert.equal(beatsSaid(beatsOf(view, { chapter: 'c1', frames: ['c1.b1.f1'] })), 'Beat 1');
  // beats that do not follow one another are said apart
  assert.equal(beatsSaid([2, 4, 5]), 'Beats 2, 4–5');
  assert.equal(beatsSaid([1, 3]), 'Beats 1, 3');
  // a picture of a chapter the plan no longer has says nothing
  assert.deepEqual(beatsOf(view, { chapter: 'c9', frames: ['c9.b1.f1'] }), []);
  assert.equal(beatsSaid([]), '');
});
