import { Circuit } from "./circuit.js";
import { b } from "@x/b";
import fs from "node:fs/promises";
import type { Shape } from "./types.js";
import leftPad from "left-pad";

export async function serve() {
  const mod = await import("./lazy.js");
  return new Circuit();
}
