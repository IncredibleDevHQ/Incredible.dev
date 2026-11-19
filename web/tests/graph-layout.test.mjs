import assert from "node:assert/strict";
import test from "node:test";
import {readFileSync} from "node:fs";
import vm from "node:vm";

const script = readFileSync(new URL("../../src/design_agent/episode/components/graph.js", import.meta.url), "utf8");
for (const variant of ["hub", "network"]) {
  test(variant + " bounds captions by the available space on both sides of a node", () => {
    const left = 60, w = 1320;
    const items = Array.from({length: 8}, (_, i) => ({id: String(i), what: "A long description for node " + i}));
    vm.runInNewContext(script, {
      variant, left, right: left + w, w, h: 960, top: 60, size: 44, brief: {}, items, colors: {}, tl: {fromTo() {}},
      words: o => o.what, node() {}, at: () => 0, participant() {},
      label(name, x, y, width) {
        assert.ok(x - width / 2 >= left && x + width / 2 <= left + w, name);
        return {setAttribute() {}};
      }
    });
  });
}
