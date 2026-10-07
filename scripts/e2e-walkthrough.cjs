// End-to-end walkthrough: drive a real browser through onboarding, portfolio selection, the main
// interface, and a reload, capturing a screenshot per step and reporting JS errors at the end.
//
// Usage: node scripts/e2e-walkthrough.cjs
// Requires the dev server on localhost:3000 (make dev).
//
// Playwright is borrowed from a sibling checkout rather than installed here; override with PLAYWRIGHT_PATH.

const path = require("path");
const fs = require("fs");

const PLAYWRIGHT =
  process.env.PLAYWRIGHT_PATH ||
  "~/Documents/留学agent/web/node_modules/@playwright/test";
const { chromium } = require(PLAYWRIGHT);

const ROOT = path.resolve(__dirname, "..");
const OUT = path.join(ROOT, "docs/screenshots");
const BASE = process.env.BASE_URL || "http://localhost:3000";

fs.mkdirSync(OUT, { recursive: true });

(async () => {
  // The profile now lives on the server, so a walkthrough with no backend would drive a page whose
  // profile never loads and report success for the empty version of every assertion below. Fail
  // here instead, with the address that was tried.
  try {
    const response = await fetch(`${BASE}/api/profile`);
    if (!response.ok) throw new Error(`GET /api/profile responded ${response.status}`);
    await response.json();
  } catch (error) {
    console.error(
      `后端不可达：GET ${BASE}/api/profile 失败（${error.message}）。` +
        "先运行 make dev（同时启动前端与 :8000 上的后端），再跑 make screenshots。",
    );
    process.exitCode = 1;
    return;
  }

  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const errors = [];
  /**
   * Errors this run caused on purpose, listed separately from the ones it is checking for.
   *
   * The block near the end answers one write with a `500` to prove the page reports a failed save. The
   * browser logs that response as a console error, and it is the run's own doing rather than the
   * page's defect. Counting it would make the deliberate failure indistinguishable from an accidental
   * one, so it is labelled and excluded from the exit code — printed, because a run that injects errors
   * should still say so.
   */
  const injected = [];
  const record = (entry) => (injectingFailure ? injected : errors).push(entry);
  let injectingFailure = false;
  page.on("console", (m) => m.type() === "error" && record("console: " + m.text()));
  page.on("pageerror", (e) => record("pageerror: " + e.message));

  /**
   * The roadmap write path's traffic, captured from the first request of the run.
   *
   * Registered before the first `goto` on purpose. A page that already has the rows writes nothing,
   * and one that has none writes as it mounts — so a capture installed later sees an empty list and
   * every assertion built on it would pass by measuring nothing. The two arrays are the evidence for
   * the checks near the end of the run.
   */
  const taskPuts = [];
  const taskPatches = [];
  await page.route(/\/api\/roadmap\/tasks/, async (route) => {
    const request = route.request();

    const body = JSON.parse(request.postData() || "null");
    if (request.method() === "PUT") {
      taskPuts.push({ url: request.url(), body });
    }
    else if (request.method() === "PATCH") taskPatches.push({ url: request.url(), body });
    await route.continue();
  });

  const shot = async (name) => {
    await page.screenshot({ path: path.join(OUT, `${name}.png`) });
    console.log("shot:", name);
  };
  /**
   * Choose an onboarding option by its leading label.
   *
   * The accessible name of an option includes its hint, and 高中's hint reads 申请本科. A substring
   * match on 本科 therefore selected 高中 and quietly produced a wrong demo profile.
   */
  const chooseOption = async (label) => {
    await page
      .locator("button.option")
      .filter({ hasText: new RegExp(`^\\s*${label}`) })
      .first()
      .click();
    await page.waitForTimeout(250);
  };
  const clickText = async (t) => {
    await page.getByRole("button", { name: t, exact: false }).first().click();
    await page.waitForTimeout(250);
  };
  /**
   * Assert, rather than print.
   *
   * The console.log lines below are evidence for a human reading the run; a `console.log` cannot gate
   * anything, so it is never the check itself. This one fails the run and names what disagreed. The
   * failure is deferred to the end (process.exitCode is read after the browser closes) so the rest of
   * the walkthrough still produces its screenshots and its error list.
   */
  const failures = [];
  const skipped = [];
  /**
   * `options.selector` marks a check whose subject may legitimately not exist in this run.
   *
   * A skipped check prints as such and is neither a pass nor a failure, so a run that could not
   * exercise a claim says so out loud instead of counting as evidence for it. It is not a way to make
   * a failing check pass: the check still has to be written so that it fails whenever its subject is
   * there and the behaviour is wrong.
   */
  const check = (name, ok, detail, options = {}) => {
    if (options.selector) {
      console.log(name + ": 跳过", detail === undefined ? "" : JSON.stringify(detail));
      skipped.push(name);
      return;
    }
    console.log(name + ":", ok ? "是" : "否", detail === undefined ? "" : JSON.stringify(detail));
    if (!ok) failures.push(name + (detail === undefined ? "" : " " + JSON.stringify(detail)));
  };

  await page.goto(BASE, { waitUntil: "networkidle" });
  await shot("01-step1-education");

  await chooseOption("本科");
  await shot("02-step2-origin");

  await chooseOption("国内院校");
  await page.locator("input").first().fill("北京邮电");
  await page.waitForTimeout(400);
  await shot("03-step3-school-detected");
  await clickText("继续");

  await page.locator("input").first().fill("软件工程");
  await clickText("继续");

  await page.locator('input[type="number"]').first().fill("82");
  await page.waitForTimeout(300);
  await shot("04-step5-gpa");
  await clickText("继续");

  await chooseOption("授课型硕士");
  await clickText("继续");
  await chooseOption("计算机与数据");
  await shot("05-step7-field");
  await clickText("继续");

  await page.locator("input").first().fill("IELTS 6.5");
  await clickText("继续");
  await chooseOption("20–30 万");
  await clickText("继续");
  await chooseOption("2027 S1");
  await shot("06-step10-intake");

  await clickText("生成我的方案");
  await page.waitForTimeout(900);
  await shot("07-generating");

  await page.getByText("为你筛出的申请组合").waitFor({ timeout: 15000 });
  await page.waitForTimeout(400);
  await shot("08-portfolio");
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await page.waitForTimeout(300);
  await shot("09-portfolio-bottom");

  await clickText("确认组合");
  await page.getByText("申请流程").first().waitFor({ timeout: 15000 });
  await page.waitForTimeout(500);
  await shot("10-flow");

  await clickText("语言准备");
  await page.waitForTimeout(300);
  await shot("11-flow-language");

  // The tick is now a `PATCH` to the row's own id, and the row's id only exists once the page has read
  // the rows the recomputation created — so this waits for the write path to land before asserting the
  // control moved. `check()` rather than `click()`: it is the assertion that the tick stuck, and it
  // waits for the state change instead of trusting the click.
  await page.locator('input[type="checkbox"]').first().check({ timeout: 15000 });
  await page.waitForTimeout(300);
  await shot("12-material-checked");

  await clickText("首页");
  await page.waitForTimeout(300);
  await shot("13-home");

  await clickText("留学顾问");
  await page.waitForTimeout(400);
  await shot("14-advisor-empty");

  await page.getByPlaceholder("给留学顾问发消息…").fill("帮我看看现在的选校组合合不合理");
  await page.getByRole("button", { name: "发送" }).click();
  await page.waitForTimeout(900);
  await shot("15-advisor-message");

  // The account control is an avatar with a hover menu, not a tab.
  //
  // Move the pointer down through the space between the button and the menu instead of jumping
  // straight onto the menu item. A previous version positioned the menu with a top offset, which left
  // that strip belonging to neither element: crossing it fired mouseleave and the menu vanished
  // before the pointer arrived.
  const account = page.getByRole("button", { name: "账户" });
  const box = await account.boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.waitForTimeout(200);
  await page.mouse.move(box.x + box.width / 2, box.y + box.height + 4, { steps: 6 });
  await page.mouse.move(box.x + box.width / 2, box.y + box.height + 24, { steps: 6 });
  await page.waitForTimeout(250);

  const menuHeld = await page.getByRole("button", { name: "个人信息", exact: true }).isVisible().catch(() => false);
  console.log("指针移向菜单后仍然打开:", menuHeld ? "是" : "否");
  await shot("16-account-menu");

  await page.getByRole("button", { name: "个人信息", exact: true }).click();
  await page.getByText("每条都能单独改").waitFor({ timeout: 10000 });
  await page.waitForTimeout(300);
  // Avatar upload: the image is downscaled in the browser and stored locally, so the header control
  // should render an img once one is chosen.
  const png = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
    "base64",
  );
  await page.locator('input[type="file"]').setInputFiles({
    name: "avatar.png",
    mimeType: "image/png",
    buffer: png,
  });
  await page.waitForTimeout(500);
  const avatarShown = (await page.locator('button[aria-label="账户"] img').count()) === 1;
  const avatarStored = await page.evaluate(() => {
    const raw = window.localStorage.getItem("offerpilot.state.v1");
    return Boolean(raw && JSON.parse(raw).avatar);
  });
  console.log("上传后头像已显示:", avatarShown ? "是" : "否");
  console.log("头像已存入本机:", avatarStored ? "是" : "否");

  // Guard against the option-selection bug above: the demo profile must say 本科, not 高中.
  const educationOk = await page
    .locator("div", { hasText: /^当前学历/ })
    .last()
    .innerText()
    .then((t) => /本科/.test(t) && !/高中/.test(t))
    .catch(() => false);
  console.log("当前学历识别为本科:", educationOk ? "是" : "否");

  await shot("17-profile");

  // Edit a single field in place instead of walking the onboarding again.
  await page.getByRole("button", { name: "编辑语言成绩" }).click();
  await page.waitForTimeout(200);
  await page.getByPlaceholder("例如：IELTS 6.5").fill("IELTS 7.0");
  await shot("18-profile-editing");
  await page.getByRole("button", { name: "保存" }).click();
  await page.waitForTimeout(300);
  const saved = await page.getByText("IELTS 7.0").isVisible().catch(() => false);
  console.log("单条编辑保存后生效:", saved ? "是" : "否");
  await shot("19-profile-saved");

  await page.getByRole("button", { name: "账户" }).hover();
  await page.waitForTimeout(250);
  await page.getByRole("button", { name: "设置", exact: true }).click();
  await page.getByText("数据说明").first().waitFor({ timeout: 10000 });
  await page.getByText("隐私政策").first().click();
  await page.waitForTimeout(300);
  await shot("20-settings");

  // No verification markers should remain anywhere in the interface.
  const bodyText = await page.locator("body").innerText();
  const markers = ["待核验", "待人工核验", "尚未逐条核验"].filter((m) => bodyText.includes(m));
  console.log("残留的数据核验标记:", markers.length ? markers.join(" / ") : "无");

  // Whether progress survives a reload (localStorage persistence). Run before the site data is
  // cleared, because that clear is what the next block is about.
  await page.reload({ waitUntil: "networkidle" });
  await page.waitForTimeout(700);
  const kept = await page
    .getByText("申请流程")
    .first()
    .isVisible()
    .catch(() => false);
  console.log("刷新后仍在主流程（localStorage 生效）:", kept);
  await shot("21-after-reload");

  // The profile must now survive without localStorage: reload after clearing site data and the
  // server-side copy should still answer. This runs last, because the clear also resets the stage
  // that still lives on localStorage and the browser ends up back in onboarding.
  await page.evaluate(() => window.localStorage.clear());
  await page.reload({ waitUntil: "networkidle" });
  await page.waitForTimeout(800);
  const serverProfile = await page.evaluate(async () => {
    const response = await fetch("/api/profile");
    return response.json();
  });
  console.log("清空 localStorage 后服务端仍有档案:", serverProfile.schoolName ? "是" : "否");

  // The assertion above only proves the server still holds a row. Clearing localStorage also reset
  // the stage, so the reload landed back on onboarding, and whether the UI *reads* that row is what
  // this line settles. The school field sits two steps in, and the value it has to show is the one
  // the server just answered with: the walker reads that value back from the API rather than
  // expecting a copy this script typed in.
  await page
    .locator("button.option")
    .filter({ hasText: /^\s*本科/ })
    .first()
    .click();
  await page.waitForTimeout(250);
  await page
    .locator("button.option")
    .filter({ hasText: /^\s*国内院校/ })
    .first()
    .click();
  await page.waitForTimeout(250);
  const serverSchoolName = await page.evaluate(
    async () => (await (await fetch("/api/profile")).json()).schoolName,
  );
  const shownSchoolName = await page
    .locator('input[placeholder="例如：北京邮电大学"]')
    .first()
    .inputValue()
    .catch(() => null);
  const restoredOk = Boolean(serverSchoolName) && shownSchoolName === serverSchoolName;
  console.log(
    "重新打开后档案已从服务端恢复:",
    restoredOk ? "是" : "否",
    JSON.stringify({ expected: serverSchoolName, actual: shownSchoolName }),
  );
  await shot("22-profile-restored-from-server");

  // The roadmap definition comes from the server, so the rendered phases have to match the served
  // ones — count and names, not merely "something rendered".
  //
  // The localStorage clear above also reset the stage, so the reload after it lands in onboarding and
  // the roadmap is not on screen at all. Putting the stage back into storage first is what makes the
  // reload a genuine cold start of the main interface with browser storage otherwise empty: the page
  // mounts, fetches the definition, builds the roadmap, and only then is anything counted.
  //
  // The expected value is read from the API in the same reloaded page rather than hardcoded, because a
  // hardcoded 7 would pass against a stale build and would have to be edited every time the definition
  // grows. That read is allowed to fail: a run against a broken definition route is a run where the
  // page is *supposed* to fall back, and reporting that is this block's job. Crashing on the read
  // instead would fail the run without saying which of the two things was wrong.
  await page.evaluate(() => {
    window.localStorage.setItem("offerpilot.state.v1", JSON.stringify({ stage: "app" }));
  });
  await page.reload({ waitUntil: "networkidle" });
  await page.getByText("申请流程").first().waitFor({ timeout: 15000 });
  await page.waitForTimeout(500);

  const readDefinition = () =>
    page.evaluate(async () => {
      // The marker separates this read from the page's own request for the same route. Without it the
      // two are indistinguishable, so a run that stubs the route cannot make the page and this check
      // disagree — and a check that cannot disagree with the page proves nothing about the page.
      const response = await fetch("/api/roadmap?from=walkthrough");
      if (!response.ok) return { ok: false, status: response.status };
      const body = await response.json();
      return { ok: true, phases: body.phases ?? [] };
    });
  let definition = await readDefinition();
  // One retry: this read races nothing in particular today, but a half-open route is not the condition
  // the assertion is about.
  if (!definition.ok) definition = await readDefinition();

  const renderedPhases = await page.evaluate(() => {
    const items = [...document.querySelectorAll("ol > li")];
    return items
      .map((li) => li.querySelector("strong")?.innerText?.trim() ?? null)
      .filter((title) => title !== null);
  });

  // Whether the page is showing the built-in copy is read first: it is the page's own answer, and the
  // condition that decides which of the two claims below is the one this run has to make.
  const fallbackNotice = await page
    .getByText("路线图定义未能从服务器读取")
    .first()
    .isVisible()
    .catch(() => false);

  if (definition.ok) {
    // The definition is reachable, so the page has to be rendering exactly it, in its order. A page
    // that never fetched, one that silently fell back to the six built-in phases, and one that dropped
    // a phase all disagree with the served list here.
    const servedTitles = definition.phases.map((p) => p.title);
    check(
      "清空浏览器存储并重载后路线图仍渲染，且阶段与接口一致",
      servedTitles.length > 0 && JSON.stringify(renderedPhases) === JSON.stringify(servedTitles),
      { served: servedTitles, rendered: renderedPhases },
    );
    // The same condition from the other side: the page says out loud when it is showing the built-in
    // copy, so the absence of that notice is what proves these phases came from the server.
    check("路线图由服务端定义渲染（未显示内置副本提示）", !fallbackNotice);
  } else {
    // The definition could not be fetched, so the page is required to keep rendering and to say which
    // copy it used. A blank screen and a silent fallback are both failures here.
    check(
      `定义接口不可用时（HTTP ${definition.status}）路线图仍渲染且说明用了内置副本`,
      renderedPhases.length > 0 && fallbackNotice,
      { rendered: renderedPhases, fallbackNotice },
    );
  }
  // No screenshot of its own: 21-after-reload already shows this exact view, and a second identical
  // image would be churn rather than evidence. The two lines above are the record.

  // ---------------------------------------------------------------------------------------------
  // The recomputation write path (M2b task 4): a tick reaches the server, survives a reload, and
  // survives a recomputation; a failed write is visible.
  //
  // The block works on the subject this page already has, which is the subject the blocks above have
  // been using. That is deliberate rather than a shortcut: a reload is the state the claim is about,
  // and a subject whose rows already exist on the server is exactly the case where a recomputation
  // must leave them alone. Its rows are all `system` when the walkthrough is run against a database
  // that has not seen this browser before, and the ticks it makes are the only `user` rows it creates.
  //
  // Every check here is a `check()`, not a `console.log`: each one can fail the run and names what
  // disagreed. The claims are the design's acceptance criteria — section 8.3's "a recomputation does
  // not lose completion state", from a reload and from a recompute — plus the visible-failure rule.
  // ---------------------------------------------------------------------------------------------
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  /** The server's own rows for the current subject, as `GET /api/roadmap` serves them. */
  const readTasks = () =>
    page.evaluate(async () => {
      const response = await fetch("/api/roadmap?from=walkthrough-tasks");
      if (!response.ok) return null;
      return (await response.json()).tasks ?? [];
    });

  await page.reload({ waitUntil: "networkidle" });
  await page.getByText("申请流程").first().waitFor({ timeout: 15000 });
  await page.waitForTimeout(400);
  // From here on the captures describe this block alone. The arrays were also collecting the traffic
  // of the blocks above, and the first `PATCH` in that list belongs to the tick those blocks made —
  // which is how a check that read `taskPatches[0]` ended up asserting against the wrong row.
  await sleep(1200);
  taskPuts.length = 0;
  taskPatches.length = 0;

  // The first load of a subject with no rows on the server is the case that triggers a recomputation,
  // so the rows have to appear without anything being ticked. A subject that already has rows writes
  // nothing, which the last check in this block pins.
  let freshRows = [];
  for (let i = 0; i < 20 && freshRows.length === 0; i += 1) {
    await sleep(250);
    freshRows = (await readTasks()) ?? [];
  }
  check("重载后服务端持有本主体的任务行", freshRows.length > 0 && taskPuts.length <= 1, {
    puts: taskPuts.length,
    rows: freshRows.length,
  });
  // Every other row below is one this block writes, so it is `system`; the walkthrough's own earlier
  // tick is the single `user` row left over. The check names it rather than tolerating it, so a
  // recomputation that silently re-owned a human's row would fail here.
  const foreignRows = freshRows.filter((row) => row.origin !== "system");
  check(
    "服务端的行除申请人自己勾选的那条外，全部为 system 归属",
    foreignRows.length <= 1 && foreignRows.every((row) => row.origin === "user"),
    foreignRows.map((row) => [row.materialKey, row.origin]),
  );
  // The applicable keys are what tells the server "this key still applies" apart from "this payload
  // does not mention it" — the distinction §3.8 turns on. The check is made on the write this block
  // triggers just below, because a subject whose rows already exist correctly writes nothing, and this
  // block cannot force one without moving the profile. Skipped, not passed, when the page's read never
  // wrote; a check that read an absent payload would be green on no evidence.
  const keysCheck = (put) => {
    const body = put?.body ?? null;
    return (
      Array.isArray(body?.applicableKeys) &&
      Array.isArray(body?.rows) &&
      body.applicableKeys.length >= body.rows.length
    );
  };

  // Tick a material. It goes through PATCH, never through the replacement, which is what keeps the
  // applicant's own mark out of the recomputation's reach.
  //
  // The phase the first tick lands in is read off the screen rather than assumed: the page opens on
  // 锁定申请组合, and the block later needs a *different* phase to fail a write in, because every
  // material of the claimed one is checked by then and a checkbox that is already checked is not a
  // control `check()` can act on.
  const roadmapPhases = await page.evaluate(() =>
    [...document.querySelectorAll("ol > li")]
      .map((li) => li.querySelector("strong")?.innerText?.trim())
      .filter(Boolean),
  );
  /** The phase the detail panel is showing: the card the page marks as selected. */
  const selectedPhase = () =>
    page.evaluate(() => {
      const card = [...document.querySelectorAll("ol > li")].find((li) =>
        li.querySelector("button")?.className.includes("border-2"),
      );
      return card?.querySelector("strong")?.innerText?.trim() ?? null;
    });
  const tickedPhase = await selectedPhase();
  const tickedBox = page.locator('input[type="checkbox"]').first();
  const tickedLabel = (await tickedBox.locator("xpath=ancestor::label[1]").innerText()).split("\n")[0].trim();
  await tickedBox.check();
  await sleep(800);
  check("勾选材料通过 PATCH 写单条，而不是整体替换", taskPatches.length === 1, taskPatches);
  check(
    "勾选请求的正文把该行标为 completed",
    taskPatches[taskPatches.length - 1]?.body?.status === "completed",
    taskPatches[taskPatches.length - 1]?.body,
  );
  // The last one, not the first: the captures were reset above, so any earlier `PATCH` is a leftover
  // from a block with its own subject, and reading the first would assert about the wrong row.
  const tickedPatch = taskPatches[taskPatches.length - 1] ?? { url: "" };
  const tickedId = String(tickedPatch.url).split("/").pop();
  let tickedRow = ((await readTasks()) ?? []).find((row) => row.id === tickedId);
  check(
    "被勾选的行在服务端变为 completed，且归属转为 user",
    tickedRow?.status === "completed" && tickedRow?.origin === "user" && Boolean(tickedRow?.completedAt),
    tickedRow,
  );

  // Move the profile so the applicable material set changes, which is the second and only other
  // reason to recompute. 研究型硕士 makes the research-plan material apply, and the recomputation is
  // required to report that as a new key.
  const beforeKeys = new Set(((await readTasks()) ?? []).map((row) => row.materialKey));
  const putsBeforeDegree = taskPuts.length;
  await page.getByRole("button", { name: "账户" }).hover();
  await page.waitForTimeout(250);
  await page.getByRole("button", { name: "个人信息", exact: true }).click();
  await page.getByText("每条都能单独改").waitFor({ timeout: 10000 });
  await page.getByRole("button", { name: "编辑目标学位" }).click();
  const degreeSelect = page.locator("select").first();
  const degreeOptions = await degreeSelect.locator("option").evaluateAll((nodes) =>
    nodes.map((node) => node.value),
  );
  const nextDegree = degreeOptions.includes("研究型硕士") ? "研究型硕士" : degreeOptions[1];
  await degreeSelect.selectOption(nextDegree);
  await page.getByRole("button", { name: "保存" }).first().click();
  for (let i = 0; i < 20 && taskPuts.length === putsBeforeDegree; i += 1) await sleep(250);
  check(
    "档案改变适用材料后触发一次新的重算",
    taskPuts.length > putsBeforeDegree,
    { before: putsBeforeDegree, after: taskPuts.length, degree: nextDegree },
  );
  const secondPut = taskPuts[taskPuts.length - 1] ?? { body: null };
  // The applicable keys are what tells the server "this key still applies" apart from "this payload
  // does not mention it" — the distinction §3.8 turns on. It is checked on the write this block just
  // caused, and skipped when the profile edit produced no new write at all: reading the previous
  // payload would be green on a request this block did not make.
  check(
    "写入请求同时带上 applicableKeys（服务端据此区分「不再适用」与「本次未提及」）",
    keysCheck(secondPut),
    { keys: secondPut.body?.applicableKeys?.length, rows: secondPut.body?.rows?.length },
    { selector: taskPuts.length <= putsBeforeDegree },
  );
  const secondKeys = new Set(secondPut.body?.applicableKeys ?? []);
  const addedKeys = [...secondKeys].filter((key) => !beforeKeys.has(key));
  check(
    "这次写入的 applicableKeys 反映了新的适用材料集合",
    addedKeys.length > 0,
    { addedKeys, keys: secondKeys.size },
  );

  // The heart of the origin rule: the row the applicant claimed is not in the replacement's rows, so
  // the recomputation cannot have rewritten it.
  check(
    "重算的替换请求不包含申请人已勾选的行（origin 规则）",
    Array.isArray(secondPut.body?.rows) &&
      secondPut.body.rows.every((row) => row.materialKey !== tickedRow?.materialKey),
    { rows: secondPut.body?.rows?.length ?? 0, ticked: tickedRow?.materialKey },
  );
  const afterRecompute = ((await readTasks()) ?? []).find((row) => row.id === tickedId);
  check(
    "重算后该行仍是 completed，completedAt 未被重写",
    afterRecompute?.status === "completed" &&
      afterRecompute?.completedAt === tickedRow?.completedAt &&
      afterRecompute?.origin === "user",
    { after: afterRecompute, before: tickedRow, label: tickedLabel },
  );
  // The same claim as the check above, read from the other side: the recomputation did not re-own any
  // row, and the set of rows the applicant owns is exactly what it was plus the tick this block made.
  const ownedRows = ((await readTasks()) ?? []).filter((row) => row.origin === "user");
  check(
    "重算没有把申请人拥有的行改成自己所有",
    ownedRows.some((row) => row.id === tickedId) && ownedRows.length <= 2,
    ownedRows.map((row) => [row.materialKey, row.origin]),
  );

  // A failed write has to be visible. The next tick is answered with a 500, so the page cannot have
  // stored it and the applicant must not be left believing it did.
  const rejectNextPatch = async (route) => {
    if (route.request().method() === "PATCH") {
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ detail: "walkthrough: forced failure" }),
      });
      return;
    }
    await route.continue();
  };
  await page.route("**/api/roadmap/tasks/*", rejectNextPatch);
  injectingFailure = true;
  // A phase whose materials the block has not ticked yet, and the first one that is not the phase the
  // first tick claimed: the material is read out of the list rather than assumed, so the tick cannot
  // land on a control that is already checked (which `check()` would refuse) or on the phase the
  // reload below has to bring back.
  const untickedPhase = roadmapPhases.find((title) => title !== tickedPhase);
  await clickText("流程进度");
  await page.waitForTimeout(200);
  await clickText(untickedPhase);
  await page.waitForTimeout(300);
  const failedBox = page.locator('input[type="checkbox"]:not(:checked)').first();
  const failedLabel = (await failedBox.locator("xpath=ancestor::label[1]").innerText()).split("\n")[0].trim();
  // The material the control names, read off the server's own rows rather than the screen: the
  // checkbox carries the label, and the row carries both the label and the key. Matching on the label
  // is what makes the failed tick's row identifiable without assuming which row the page picked.
  const completedBefore = ((await readTasks()) ?? []).filter((row) => row.status === "completed").length;
  await failedBox.check();
  await sleep(900);
  const failureNotice = await page
    .getByText("没有保存到服务器")
    .first()
    .isVisible()
    .catch(() => false);
  const failedStillUnchecked = await failedBox.isChecked().catch(() => null);
  check("写入失败时页面给出可见提示", failureNotice);
  check("写入失败后勾选被回退，界面不与服务器不一致", failedStillUnchecked === false, {
    checked: failedStillUnchecked,
  });
  await page.unroute("**/api/roadmap/tasks/*", rejectNextPatch);
  injectingFailure = false;
  await page.waitForTimeout(700);
  const failedRows = (await readTasks()) ?? [];
  // The count of completed rows is what the server's own rows say, and it has to be the count from
  // before this tick: the write was rejected, so nothing about it may have reached the database. A
  // count rather than a key because the row this tick was for is not one either this script or the
  // page has an id for until it is stored.
  check(
    "失败的那一次勾选没有留在服务端",
    failedRows.filter((row) => row.status === "completed").length === completedBefore,
    { before: completedBefore, after: failedRows.filter((row) => row.status === "completed").length, label: failedLabel },
  );

  // A reload must show that same tick, because it comes from the server rather than this device.
  await page.reload({ waitUntil: "networkidle" });
  await page.getByText("申请流程").first().waitFor({ timeout: 15000 });
  await page.waitForTimeout(500);
  await page.getByRole("button", { name: "流程进度" }).click();
  await clickText(tickedPhase);
  await page.waitForTimeout(400);
  const restoredBox = page.locator('input[type="checkbox"]').first();
  const restoredChecked = await restoredBox.isChecked().catch(() => null);
  check("刷新后勾选状态仍在（完成状态来自服务端）", restoredChecked === true, {
    checked: restoredChecked,
    label: tickedLabel,
    phase: tickedPhase,
  });
  const putsAfterReload = taskPuts.length;
  await sleep(600);
  check(
    "服务端已有行时，刷新不会再次写入（不做无谓重算）",
    taskPuts.length === putsAfterReload,
    { before: putsAfterReload, after: taskPuts.length },
  );
  await shot("23-task-tick-survives-reload");

  console.log("\n=== JS 错误 ===");
  console.log(errors.length ? errors.join("\n") : "无");
  if (injected.length) console.log("本次走查有意注入的错误:\n" + injected.join("\n"));
  if (skipped.length) console.log("跳过（本次运行没有对应的前提）:\n" + skipped.join("\n"));

  await browser.close();
  if (failures.length) console.error("断言未通过:\n" + failures.join("\n"));
  if (errors.length || failures.length) process.exitCode = 1;
})();
