import test from "node:test";
import { selfCheck } from "./savedPersonas.ts";

test("saved persona storage self-check passes", () => {
  selfCheck();
});
