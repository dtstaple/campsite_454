import { test } from "node:test";
import assert from "node:assert/strict";
import {
  flown,
  OFF,
  panelClosed,
  pressed,
  readStored,
  STORAGE_KEY,
  writeStored,
} from "../src/map/threeD.ts";

function memory(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  return {
    data,
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => void data.set(key, value),
  };
}

const throwing = {
  getItem: () => {
    throw new Error("blocked");
  },
  setItem: () => {
    throw new Error("blocked");
  },
};

test("a 3D button press is the user's choice", () => {
  assert.deepEqual(pressed(true), { on: true, by: "user" });
  assert.deepEqual(pressed(false), OFF);
});

test("Fly the trail turns 3D on without taking over the user's choice", () => {
  assert.deepEqual(flown(OFF), { on: true, by: "flythrough" });
  assert.deepEqual(flown(pressed(true)), { on: true, by: "user" });
});

test("closing the trail panel only undoes 3D the flythrough turned on", () => {
  assert.deepEqual(panelClosed(flown(OFF)), OFF);
  assert.deepEqual(panelClosed(pressed(true)), pressed(true));
  assert.deepEqual(panelClosed(flown(pressed(true))), pressed(true));
  assert.deepEqual(panelClosed(OFF), OFF);
});

test("the user's choice is remembered across reloads", () => {
  const store = memory();
  writeStored(store, pressed(true));
  assert.deepEqual(readStored(store), pressed(true));
  writeStored(store, pressed(false));
  assert.equal(store.data.get(STORAGE_KEY), "off");
  assert.deepEqual(readStored(store), OFF);
});

test("a flythrough's 3D is never remembered", () => {
  const store = memory({ [STORAGE_KEY]: "off" });
  writeStored(store, flown(OFF));
  assert.deepEqual(readStored(store), OFF);
});

test("blocked or missing storage starts flat and never throws", () => {
  assert.deepEqual(readStored(throwing), OFF);
  assert.deepEqual(readStored(undefined), OFF);
  assert.doesNotThrow(() => writeStored(throwing, pressed(true)));
  assert.deepEqual(readStored(memory({ [STORAGE_KEY]: "garbage" })), OFF);
});
