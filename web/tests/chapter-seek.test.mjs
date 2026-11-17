import assert from "node:assert/strict";
import test from "node:test";
import { spanAt } from "../src/components/episode/chapterSeek.ts";

test("a narrated beat starts even when rounded durations overlap its start", () => {
  const spans = [{start: 0, seconds: 12.186}, {start: 90.112 - 77.927, seconds: 13.377}];
  assert.equal(spanAt(spans, spans[1].start - 0.001), spans[0]);
  assert.equal(spanAt(spans, spans[1].start), spans[1]);
});

test("a rounding gap holds the preceding beat until the next one starts", () => {
  const spans = [{start: 0, seconds: 2}, {start: 2.001, seconds: 3}, {start: 5.001, seconds: 1}];
  assert.equal(spanAt(spans, 2), spans[0]);
  assert.equal(spanAt(spans, 2.001), spans[1]);
  assert.equal(spanAt(spans, 6.001), spans[2]);
});
