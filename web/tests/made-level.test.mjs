import assert from 'node:assert/strict';
import test from 'node:test';
import { madeLevel } from '../src/episode.ts';

const unit = (level, picture) => ({ kind: 'picture', level, frames: ['c1.b1.f1'], picture: { status: 'none', level: '', motion: null, stale: false, reworded: false, ...picture } });

test("a picture's switch says how it was made, not how the film's pictures are made now", () => {
  // the film moved on to motion graphics after this one was drawn simple
  assert.equal(madeLevel(unit('rich', { status: 'made', level: 'simple' })), 'simple');
  assert.equal(madeLevel(unit('simple', { status: 'go', level: 'rich' })), 'rich');
  // out of date or stopped, it is still what it was made as
  assert.equal(madeLevel(unit('simple', { status: 'made', level: 'rich', stale: true })), 'rich');
  assert.equal(madeLevel(unit('simple', { status: 'failed', level: 'rich' })), 'rich');
});

test('one made before the level was kept is motion graphics when it has a motion plan', () => {
  assert.equal(madeLevel(unit('simple', { status: 'made', motion: { device: '', world: '', shots: [] } })), 'rich');
  assert.equal(madeLevel(unit('rich', { status: 'made' })), 'simple');
});

test('a picture not made yet is as it will be made', () => {
  assert.equal(madeLevel(unit('rich', { status: 'none' })), 'rich');
  assert.equal(madeLevel(unit('simple', { status: 'none' })), 'simple');
});

test("a beat's one mark is the most pressing thing about its picture, and plain ones have none", async () => {
  const { markOf } = await import('../src/episode.ts');
  const mark = (level, picture) => markOf(unit(level, picture))?.kind ?? null;
  assert.equal(mark('rich', { status: 'failed', level: 'rich' }), 'failed');
  assert.equal(mark('rich', { status: 'go', level: 'rich' }), 'go');
  assert.equal(mark('rich', { status: 'making', level: 'rich' }), 'making');
  assert.equal(mark('simple', { status: 'made', level: 'simple', stale: true }), 'changed');
  assert.equal(mark('simple', { status: 'made', level: 'simple', reworded: true }), 'changed');
  assert.equal(mark('simple', { status: 'made', level: 'rich' }), 'rich');
  // a simple picture that is made, and one not asked for yet, say nothing
  assert.equal(mark('rich', { status: 'made', level: 'simple' }), null);
  assert.equal(mark('rich', { status: 'none' }), null);
  // what a mark says is what the picture's card says
  assert.equal(markOf(unit('rich', { status: 'go', level: 'rich' }))?.said, 'Needs your go');
  assert.equal(markOf(unit('simple', { status: 'made', level: 'rich' }))?.said, 'Motion graphics');
  assert.equal(markOf(undefined), null);
});

test('a chapter turns its mark while any picture of it is being made, whatever else it waits on', async () => {
  const { chapterMaking } = await import('../src/episode.ts');
  const chapter = { id: 'c1' };
  const of = (...statuses) => ({ waiting: [], units: statuses.map((status) => ({ ...unit('simple', { status }), chapter: 'c1' })) });
  // one waits on the person's go and one is being drawn again: the chapter says the go, and turns
  assert.equal(chapterMaking(of('go', 'making'), chapter), true);
  assert.equal(chapterMaking(of('made', 'queued'), chapter), true);
  assert.equal(chapterMaking(of('made', 'go', 'failed', 'none'), chapter), false);
  // another chapter's picture being made is not this one's
  assert.equal(chapterMaking({ waiting: [], units: [{ ...unit('simple', { status: 'making' }), chapter: 'c2' }] }, chapter), false);
});

test('an earlier version shows its own stills and clip, made as it was then', async () => {
  const { asVersion } = await import('../src/episode.ts');
  const stills = { 'c1.b1.f1': { id: 'old-still' } };
  const clip = { id: 'old-clip' };
  const kept = { n: 1, stills, clip, level: 'simple', builder: 'claude', generation: null, made_at: 1, seconds: 12 };
  const now = unit('rich', { status: 'making', level: 'rich', builder: 'kimi', stills: {}, clip: null, stale: true, versions: [kept] });
  const before = asVersion(now, kept);
  assert.equal(before.picture.status, 'made');
  assert.deepEqual(before.picture.stills, stills);
  assert.equal(before.picture.clip, clip);
  assert.equal(before.picture.builder, 'claude');
  assert.equal(before.picture.stale, false);
  assert.equal(madeLevel(before), 'simple');
  // the beat itself is left as it is
  assert.equal(now.picture.status, 'making');
});

test('the frame shows the version picked, and while a picture is made again the one before it', async () => {
  const { versionShown } = await import('../src/episode.ts');
  const versions = [{ n: 2 }, { n: 1 }];
  const made = unit('simple', { status: 'made', versions });
  // made, it shows itself until an earlier version is picked
  assert.equal(versionShown(made, null), undefined);
  assert.equal(versionShown(made, 1), versions[1]);
  // made again, the version it was until then stands in the frame, whether it waits or is drawn
  assert.equal(versionShown(unit('simple', { status: 'queued', versions }), null), versions[0]);
  assert.equal(versionShown(unit('simple', { status: 'posing', versions }), null), versions[0]);
  assert.equal(versionShown(unit('simple', { status: 'making', versions }), 1), versions[1]);
  // made for the first time there is nothing before it, and a version no longer kept shows nothing
  assert.equal(versionShown(unit('simple', { status: 'making', versions: [] }), null), undefined);
  assert.equal(versionShown(made, 7), undefined);
  // one that stopped shows as it stopped
  assert.equal(versionShown(unit('simple', { status: 'failed', versions }), null), undefined);
});

test('what runs now lists the work under way before the pictures waiting their turn', async () => {
  const { runningTasks, doingNow } = await import('../src/episode.ts');
  const of = (id, status, stages = []) => ({ ...unit('rich', { status, level: 'rich', stages }), id });
  const view = (units, more = {}) => ({ status: 'studio', stage: {}, film_state: {}, waiting: [], units, ...more });
  const drawing = of('c1.b2.f1', 'making', [{ id: 'motion', state: 'done' }, { id: 'draw', state: 'running' }]);
  const waiting = of('c1.b1.f1', 'queued', [{ id: 'draw', state: 'running' }]);
  const all = runningTasks(
    view([waiting, of('c1.b3.f1', 'made'), drawing, of('c2.b1.f1', 'go'), of('c2.b2.f1', 'failed'), of('c2.b3.f1', 'none')], {
      stage: { state: 'working', name: 'change' },
      film_state: { status: 'rendering' },
    }),
  );
  assert.deepEqual(all.map((t) => [t.kind, t.id, t.waiting]), [
    ['picture', 'c1.b2.f1', false],
    ['writer', 'writer', undefined],
    ['film', 'film', undefined],
    ['picture', 'c1.b1.f1', true],
  ]);
  // nothing runs once the pictures are made, waiting for a go or stopped
  assert.deepEqual(runningTasks(view([of('a', 'made'), of('b', 'go'), of('c', 'failed')])), []);
  // a plan still being written is not a turn on a plan that stands
  assert.deepEqual(runningTasks(view([], { status: 'planning', stage: { state: 'working' } })), []);
  // what a picture is on: its stage under way in a word, and its turn while it waits
  assert.equal(doingNow(drawing), 'Drawing');
  assert.equal(doingNow(waiting), 'Waiting its turn');
  assert.equal(doingNow(of('x', 'posing')), 'Taking its stills');
});
