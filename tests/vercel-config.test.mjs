import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("Vercel Services routes the web and FastAPI services on one domain", async () => {
  const config = JSON.parse(await readFile(new URL("../vercel.json", import.meta.url), "utf8"));

  assert.equal(config.experimentalServices.web.entrypoint, ".");
  assert.equal(config.experimentalServices.web.routePrefix, "/");
  assert.equal(config.experimentalServices.api.entrypoint, "api/main.py");
  assert.equal(config.experimentalServices.api.routePrefix, "/api");
});
