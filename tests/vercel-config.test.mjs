import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("Vercel Services routes the web and FastAPI services on one domain", async () => {
  const config = JSON.parse(await readFile(new URL("../vercel.json", import.meta.url), "utf8"));

  assert.equal(config.services.web.root, ".");
  assert.equal(config.services.web.framework, "nextjs");
  assert.equal(config.services.api.root, "api/");
  assert.equal(config.services.api.entrypoint, "main:app");
  assert.deepEqual(config.rewrites[0], {
    source: "/api/(.*)",
    destination: { service: "api" },
  });
});
