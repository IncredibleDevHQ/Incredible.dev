import assert from 'node:assert/strict';
import test from 'node:test';
import { clipOf, gb, importWords } from '../src/camera.ts';

const clip = (name, recorded_at, seconds) => ({ path: `/Volumes/CARD/${name}`, name, card: 'CARD', size: 1e9, seconds, recorded_at, look: '', fps: '' });
const take = (over) => ({ id: 'tk_1', n: 2, label: '', chapter: 'c1', frame: '', seconds: 600, marks: [], kept: true, video: null, audio: null, uhd: null, recording: {}, kept_at: '', created_at: 0, ...over });

test('the clip a take was recorded with is the one its time overlaps most', () => {
  const clips = [clip('C0003.MP4', 10_000, 300), clip('C0002.MP4', 4_000, 900), clip('C0001.MP4', 1_000, 120)];
  // recorded 4:10 into C0002, and it runs past C0002's end into nothing else
  assert.equal(clipOf(clips, take({ recording: { at: 4_250 } }))?.name, 'C0002.MP4');
  // a camera whose clock is a few minutes off still finds it
  assert.equal(clipOf(clips, take({ seconds: 120, recording: { at: 1_200 } }))?.name, 'C0001.MP4');
  // a take from before the studio said when it began is placed by when it was saved
  assert.equal(clipOf(clips, take({ seconds: 200, created_at: 10_250 }))?.name, 'C0003.MP4');
  // nothing near it, or a clip with no time, is no match
  assert.equal(clipOf(clips, take({ recording: { at: 50_000 } })), undefined);
  assert.equal(clipOf([clip('C0009.MP4', 0, 600)], take({ recording: { at: 100 } })), undefined);
  assert.equal(clipOf(clips, undefined), undefined);
});

test('a recording coming in says how far it has come', () => {
  const view = { takes: [take({ id: 'tk_1', n: 2 }), take({ id: 'tk_2', n: 3, label: 'Calm delivery' })] };
  assert.equal(importWords({ chapter: 'c1', take: 'tk_9', name: 'C0001.MP4', guide: '', state: 'copying', done: 3.2e9, total: 10.4e9 }, view), 'Copying · 3.2 GB of 10.4 GB');
  assert.equal(importWords({ chapter: 'c1', take: 'tk_9', name: 'C0001.MP4', guide: 'tk_1', state: 'matching' }, view), 'Matching its sound to Take 2');
  assert.equal(importWords({ chapter: 'c1', take: 'tk_9', name: 'C0001.MP4', guide: 'tk_2', state: 'matching' }, view), 'Matching its sound to Calm delivery');
  assert.equal(importWords({ chapter: 'c1', take: 'tk_9', name: 'C0001.MP4', guide: '', state: 'cutting', fraction: 0.426 }, view), 'Making its copies · 43%');
  assert.equal(importWords({ chapter: 'c1', take: 'tk_9', name: 'C0001.MP4', guide: '', state: 'failed', failure: 'The camera stopped 3 s before this take ended.' }, view), 'The camera stopped 3 s before this take ended.');
  assert.equal(gb(12_882_975), '13 MB');
});
