import { expect, test, type BrowserContext } from "@playwright/test";

const apiUrl = "http://127.0.0.1:8100";
const password = "OfferPilot123";

async function registerAndLogin(context: BrowserContext, email: string, displayName: string) {
  const registration = await context.request.post(`${apiUrl}/auth/register`, {
    data: { email, password, display_name: displayName, accepted_terms: true },
  });
  expect([201, 409]).toContain(registration.status());
  if (registration.status() === 201) {
    const payload = await registration.json() as { debug_token: string };
    const verification = await context.request.post(`${apiUrl}/auth/verify-email`, {
      data: { token: payload.debug_token },
    });
    expect(verification.ok()).toBe(true);
  }
  const login = await context.request.post(`${apiUrl}/auth/login`, { data: { email, password } });
  expect(login.ok()).toBe(true);
}

async function revokeBrowserSession(context: BrowserContext) {
  const sessionCookie = (await context.cookies()).find((cookie) => cookie.name === "offerpilot_session");
  if (!sessionCookie) throw new Error("Browser session cookie is missing");
  const response = await fetch(`${apiUrl}/auth/logout`, {
    method: "POST",
    headers: { Authorization: `Bearer ${sessionCookie.value}` },
  });
  expect(response.ok).toBe(true);
}

test("cookie session survives the recommendation, primary choice, advisor SSE, and refresh flow", async ({ context, page }) => {
  const email = `e2e-${Date.now()}@offerpilot.test`;

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "继续你的申请规划" })).toBeVisible();
  await expect(page.getByText("登录状态已失效，请重新登录。")).toHaveCount(0);

  await page.getByRole("button", { name: "注册账户" }).click();
  await page.getByLabel("你的称呼").fill("浏览器验收用户");
  await page.getByLabel("邮箱").fill(email);
  await page.getByLabel("密码（至少 8 位，包含字母和数字）").fill(password);
  await page.getByLabel("我已阅读并同意服务条款与隐私说明").check();
  await page.getByRole("button", { name: /注册并验证邮箱/ }).click();
  await expect(page.getByText("注册成功，请检查邮箱完成验证")).toBeVisible();
  await page.getByRole("button", { name: "本地环境：完成邮箱验证" }).click();
  await expect(page.getByText("邮箱验证成功，现在可以登录")).toBeVisible();

  await page.getByLabel("邮箱").fill(email);
  await page.getByLabel("密码").fill(password);
  await page.getByRole("button", { name: /^登录/ }).click();
  await expect(page.getByRole("heading", { name: "学术背景" })).toBeVisible();

  const sessionCookie = (await context.cookies()).find((cookie) => cookie.name === "offerpilot_session");
  expect(sessionCookie).toBeDefined();
  expect(sessionCookie?.httpOnly).toBe(true);
  expect(sessionCookie?.sameSite).toBe("Lax");

  await page.getByLabel("当前或最高学历院校 *").fill("浏览器测试大学");
  await page.getByLabel("专业或课程体系 *").fill("软件工程");
  await page.locator("label", { hasText: "当前学术成绩" }).locator("input").fill("82");
  await page.getByRole("button", { name: /下一步/ }).click();
  await expect(page.getByRole("heading", { name: "申请目标与个人偏好" })).toBeVisible();
  await page.getByLabel("语言成绩").fill("IELTS 7.0，单项 6.5");
  await page.getByLabel("年度预算（万元人民币）").fill("50");
  await page.getByLabel("核心课程与技能").fill("高等数学、线性代数、概率统计、数据结构、数据库、Python");
  await page.getByLabel("实习、科研与项目经历").fill("后端开发实习");
  await page.getByLabel("职业目标").fill("AI 应用工程师");
  await page.getByLabel("城市偏好").fill("悉尼优先");
  await page.getByRole("button", { name: /生成选校方案/ }).click();

  await expect(page.getByRole("heading", { name: "授课型硕士 · 计算机与数据 · 2027 S1" })).toBeVisible();
  const firstProgram = page.locator(".program-result-card").first();
  await firstProgram.getByRole("button", { name: /查看 .* 详情/ }).click();
  await expect(page.locator(".source-card")).toContainText("版本 seed-");
  await page.getByRole("button", { name: "← 返回选校方案" }).click();
  await firstProgram.getByRole("button", { name: "确定申请" }).click();
  await firstProgram.getByRole("button", { name: "☆ 设为首选" }).click();
  await expect(firstProgram.getByRole("button", { name: "★ 首选项目" })).toBeVisible();
  await expect(page.locator(".portfolio-summary")).toContainText("1 个确定申请");

  await page.getByRole("navigation", { name: "主要导航" }).getByRole("button", { name: "AI 申请顾问" }).click();
  await expect(page.getByRole("heading", { name: "把问题变成下一步行动" })).toBeVisible();
  const advisorInput = page.getByPlaceholder(/我想把入学时间改到/);
  await expect(advisorInput).toBeEnabled();
  await advisorInput.fill("UQ 数据科学的雅思和数学先修要求是什么？");
  await page.getByRole("button", { name: /^发送/ }).click();
  await expect(page.getByRole("dialog", { name: "是否使用 DeepSeek 顾问？" })).toBeVisible();
  await page.getByRole("button", { name: "拒绝并使用规则顾问" }).click();
  await expect(page.locator(".chat-message.assistant")).toHaveCount(2);
  await expect(page.locator(".chat-message.assistant").last()).toContainText("UQ");
  await expect(page.locator(".advisor-status")).toContainText("规则顾问");
  const persistedThreadsResponse = await context.request.get(`${apiUrl}/me/advisor/threads`);
  const persistedThreads = await persistedThreadsResponse.json() as Array<{ id: string; messages: unknown[] }>;
  expect(persistedThreads).toHaveLength(1);
  const persistedThreadId = persistedThreads[0].id;

  await page.reload();
  await expect(page.getByRole("heading", { name: "学术背景" })).toBeVisible();
  await expect(page.getByText("请先登录")).toHaveCount(0);
  await page.getByRole("navigation", { name: "主要导航" }).getByRole("button", { name: "历史记录" }).click();
  await expect(page.getByRole("heading", { name: "历史选校方案" })).toBeVisible();
  await page.locator(".history-list button").first().click();
  await expect(page.locator(".portfolio-summary")).toContainText("1 个确定申请");
  await page.getByRole("button", { name: "查看行动计划" }).click();
  await expect(page.getByLabel("确定申请项目分支")).toContainText("★ 首选");
  await page.getByRole("navigation", { name: "主要导航" }).getByRole("button", { name: "AI 申请顾问" }).click();
  await expect(page.locator(".chat-message.user")).toHaveCount(1);
  await expect(page.locator(".chat-message.assistant")).toHaveCount(2);
  await expect(page.locator(".chat-message.assistant").last()).toContainText("UQ");
  const resumedThreadsResponse = await context.request.get(`${apiUrl}/me/advisor/threads`);
  const resumedThreads = await resumedThreadsResponse.json() as Array<{ id: string }>;
  expect(resumedThreads).toHaveLength(1);
  expect(resumedThreads[0].id).toBe(persistedThreadId);
});

test("revoked cookies return the browser to login on refresh and protected requests", async ({ context, page }) => {
  const email = `e2e-revoked-${Date.now()}@offerpilot.test`;
  await registerAndLogin(context, email, "会话恢复用户");

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "学术背景" })).toBeVisible();

  await revokeBrowserSession(context);
  await page.reload();
  await expect(page.getByRole("heading", { name: "继续你的申请规划" })).toBeVisible();
  await expect(page.getByText("登录状态已失效，请重新登录。")).toBeVisible();
  await expect.poll(async () => (await context.cookies()).some((cookie) => cookie.name === "offerpilot_session")).toBe(false);

  await page.getByLabel("邮箱").fill(email);
  await page.getByLabel("密码").fill(password);
  await page.getByRole("button", { name: /^登录/ }).click();
  await expect(page.getByRole("heading", { name: "学术背景" })).toBeVisible();

  await revokeBrowserSession(context);
  await page.getByRole("navigation", { name: "主要导航" }).getByRole("button", { name: "AI 申请顾问" }).click();
  await expect(page.getByRole("heading", { name: "继续你的申请规划" })).toBeVisible();
  await expect(page.getByText("登录状态已失效，请重新登录。")).toBeVisible();
  await expect.poll(async () => (await context.cookies()).some((cookie) => cookie.name === "offerpilot_session")).toBe(false);
});

test("admin reviews a source diff, publishes it, and rolls back through the UI", async ({ context, page }) => {
  const email = "source-admin@offerpilot.test";
  const slug = "unsw-master-it";
  await registerAndLogin(context, email, "来源审核管理员");

  const baselineProgramResponse = await context.request.get(`${apiUrl}/programs/${slug}`);
  expect(baselineProgramResponse.ok()).toBe(true);
  const baselineProgram = await baselineProgramResponse.json() as { duration: string };
  const baselineVersionsResponse = await context.request.get(`${apiUrl}/admin/program-sources/${slug}/versions`);
  expect(baselineVersionsResponse.ok()).toBe(true);
  const baselineVersions = await baselineVersionsResponse.json() as Array<{
    version_id: string;
    content_hash: string;
    status: string;
  }>;
  const baseline = baselineVersions.find((version) => version.status === "published");
  if (!baseline) throw new Error("E2E source registry has no published baseline");
  const existingVersionIds = new Set(baselineVersions.map((version) => version.version_id));
  let createdCandidateId: string | undefined;

  try {
    await page.goto("/");
    const navigation = page.getByRole("navigation", { name: "主要导航" });
    await expect(navigation.getByRole("button", { name: "运营后台" })).toBeVisible();
    await navigation.getByRole("button", { name: "运营后台" }).click();
    await expect(page.getByRole("heading", { name: "运营后台" })).toBeVisible();

    await page.getByLabel("选择项目").selectOption(slug);
    await expect(page.getByText(/当前 SHA-256/)).toBeVisible();
    await page.getByRole("button", { name: "基于当前版本创建候选" }).click();
    const editor = page.getByLabel("候选 Program JSON");
    const draft = JSON.parse(await editor.inputValue()) as Record<string, unknown>;
    const candidateDuration = baselineProgram.duration === "2.25 年" ? "2.5 年" : "2.25 年";
    draft.duration = candidateDuration;
    await editor.fill(JSON.stringify(draft, null, 2));
    await page.getByRole("button", { name: "生成字段差异" }).click();
    await expect(page.getByText("候选已生成，请核对字段差异后再决定是否发布。")).toBeVisible();

    const candidateVersionsResponse = await context.request.get(`${apiUrl}/admin/program-sources/${slug}/versions`);
    const candidateVersions = await candidateVersionsResponse.json() as Array<{ version_id: string; status: string }>;
    createdCandidateId = candidateVersions.find((version) => version.status === "pending_review" && !existingVersionIds.has(version.version_id))?.version_id;
    if (!createdCandidateId) throw new Error("E2E candidate was not persisted");

    const pendingCard = page.locator(".source-version-pending_review").filter({ hasText: createdCandidateId });
    await expect(pendingCard).toContainText("duration");
    await expect(pendingCard).toContainText(candidateDuration);
    await pendingCard.getByLabel("审核备注").fill("Playwright 核对官网字段差异");
    await pendingCard.getByRole("button", { name: "批准发布" }).click();
    await expect(page.getByText("候选已批准并成为当前发布版本。")).toBeVisible();

    const publishedCard = page.locator(".source-version-published").filter({ hasText: createdCandidateId });
    await expect(publishedCard).toContainText(candidateDuration);
    const baselineCard = page.locator(".source-version-superseded").filter({ hasText: baseline.version_id });
    await baselineCard.getByLabel("回滚备注").fill("Playwright 验收后恢复基线内容");
    await baselineCard.getByRole("button", { name: "回滚到此版本" }).click();
    await expect(page.getByText("已回滚到所选历史内容，并创建新的发布审计版本。")).toBeVisible();

    const restoredProgram = await context.request.get(`${apiUrl}/programs/${slug}`);
    expect((await restoredProgram.json() as { duration: string }).duration).toBe(baselineProgram.duration);
  } finally {
    const versionsResponse = await context.request.get(`${apiUrl}/admin/program-sources/${slug}/versions`);
    if (versionsResponse.ok()) {
      const versions = await versionsResponse.json() as Array<{
        version_id: string;
        content_hash: string;
        status: string;
      }>;
      const created = createdCandidateId ? versions.find((version) => version.version_id === createdCandidateId) : undefined;
      if (created?.status === "pending_review") {
        await context.request.put(`${apiUrl}/admin/program-sources/${slug}/versions/${created.version_id}`, {
          data: { decision: "reject", note: "Playwright 清理未完成候选" },
        });
      }
      const current = versions.find((version) => version.status === "published");
      const baselineTarget = versions.find((version) => version.version_id === baseline.version_id);
      if (current?.content_hash !== baseline.content_hash && baselineTarget?.status === "superseded") {
        await context.request.post(`${apiUrl}/admin/program-sources/${slug}/rollback`, {
          data: { target_version_id: baseline.version_id, note: "Playwright 失败清理并恢复基线" },
        });
      }
    }
  }
});

test("advisor SSE 503 restores the draft and reuses its idempotency key", async ({ context, page }) => {
  const email = `e2e-sse-${Date.now()}@offerpilot.test`;
  const message = "请重新检查我的申请计划";
  await registerAndLogin(context, email, "SSE 失败路径用户");

  const profile = await context.request.put(`${apiUrl}/me/profile`, {
    data: {
      current_education_level: "本科",
      undergraduate_school: "浏览器测试大学",
      school_tier: "211/双一流",
      undergraduate_major: "软件工程",
      gpa: 82,
      gpa_scale: 100,
      target_degree_level: "授课型硕士",
      target_field: "计算机与数据",
      intake: "2027 S1",
      english_score: "IELTS 7.0，单项 6.5",
      coursework_summary: "高等数学、线性代数、数据结构、数据库、Python",
      experience_summary: "后端开发实习",
      career_goal: "AI 应用工程师",
      location_preferences: "悉尼优先",
      annual_budget_cny: 500000,
    },
  });
  expect(profile.ok()).toBe(true);
  const consent = await context.request.post(`${apiUrl}/me/advisor/consent`, { data: { accepted: false } });
  expect(consent.ok()).toBe(true);

  const requestKeys: string[] = [];
  await page.route("**/me/advisor/threads/*/messages/stream", async (route) => {
    requestKeys.push(route.request().headers()["idempotency-key"] ?? "");
    if (requestKeys.length === 1) {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "模拟 SSE 不可用" }),
      });
      return;
    }
    const response = await route.fetch();
    await route.fulfill({ response });
  });
  await page.goto("/");
  const navigation = page.getByRole("navigation", { name: "主要导航" });
  await expect(navigation.getByRole("button", { name: "AI 申请顾问" })).toBeVisible();
  await navigation.getByRole("button", { name: "AI 申请顾问" }).click();
  await expect(page.getByRole("heading", { name: "把问题变成下一步行动" })).toBeVisible();
  const advisorInput = page.getByPlaceholder(/我想把入学时间改到/);
  await expect(advisorInput).toBeEnabled();
  await expect(page.locator(".chat-message")).toHaveCount(1);

  await advisorInput.fill(message);
  await page.getByRole("button", { name: /^发送/ }).click();
  await expect(page.locator(".advisor-status")).toContainText("模拟 SSE 不可用");
  await expect(advisorInput).toHaveValue(message);
  await expect(advisorInput).toBeEnabled();
  await expect(page.locator(".chat-message")).toHaveCount(1);
  await expect(page.locator(".chat-loading")).toHaveCount(0);

  await page.getByRole("button", { name: /^发送/ }).click();
  await expect(advisorInput).toHaveValue("");
  await expect(page.locator(".chat-message")).toHaveCount(3);
  expect(requestKeys).toHaveLength(2);
  expect(requestKeys[0]).toMatch(/^[0-9a-f-]{36}$/);
  expect(requestKeys[1]).toBe(requestKeys[0]);

  const threadsResponse = await context.request.get(`${apiUrl}/me/advisor/threads`);
  const threads = await threadsResponse.json() as Array<{ messages: unknown[] }>;
  expect(threads).toHaveLength(1);
  expect(threads[0].messages).toHaveLength(3);
});

test("advisor tool actions render skipped work without a success check", async ({ context, page }) => {
  const email = `e2e-action-status-${Date.now()}@offerpilot.test`;
  await registerAndLogin(context, email, "动作状态用户");
  const profile = await context.request.put(`${apiUrl}/me/profile`, {
    data: {
      current_education_level: "本科",
      undergraduate_school: "浏览器测试大学",
      school_tier: "211/双一流",
      undergraduate_major: "软件工程",
      gpa: 82,
      gpa_scale: 100,
      target_degree_level: "授课型硕士",
      target_field: "计算机与数据",
      intake: "2027 S1",
    },
  });
  expect(profile.ok()).toBe(true);
  expect((await context.request.post(`${apiUrl}/me/advisor/consent`, { data: { accepted: false } })).ok()).toBe(true);

  await page.route("**/me/advisor/threads/*/messages/stream", async (route) => {
    const response = await route.fetch();
    const skippedAction = {
      tool: "update_task",
      summary: "没有找到可修改的路线图任务",
      arguments: {},
      status: "skipped",
    };
    const body = (await response.text()).split("\n\n").map((block) => {
      const event = block.split("\n").find((line) => line.startsWith("event:"))?.slice(6).trim();
      const data = block.split("\n").filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trim()).join("\n");
      if (event === "actions") return `event: actions\ndata: ${JSON.stringify([skippedAction])}`;
      if (event !== "state" || !data) return block;
      const state = JSON.parse(data) as {
        thread: { messages: Array<{ role: string; actions: unknown[] }> };
      };
      const assistant = [...state.thread.messages].reverse().find((message) => message.role === "assistant");
      if (assistant) assistant.actions = [skippedAction];
      return `event: state\ndata: ${JSON.stringify(state)}`;
    }).join("\n\n");
    await route.fulfill({ response, body });
  });

  await page.goto("/");
  await page.getByRole("navigation", { name: "主要导航" }).getByRole("button", { name: "AI 申请顾问" }).click();
  const advisorInput = page.getByPlaceholder(/我想把入学时间改到/);
  await expect(advisorInput).toBeEnabled();
  await advisorInput.fill("把不存在的任务标记完成");
  await page.getByRole("button", { name: /^发送/ }).click();

  const skippedAction = page.locator(".tool-action-skipped").last();
  await expect(skippedAction).toContainText("已跳过");
  await expect(skippedAction).toContainText("没有找到可修改的路线图任务");
  await expect(skippedAction).not.toContainText("✓");
});

test("advisor rejects a truncated SSE before state and removes the partial reply", async ({ context, page }) => {
  const email = `e2e-sse-truncated-${Date.now()}@offerpilot.test`;
  const message = "请在断线后保留这条草稿";
  await registerAndLogin(context, email, "SSE 中断用户");

  const profile = await context.request.put(`${apiUrl}/me/profile`, {
    data: {
      current_education_level: "本科",
      undergraduate_school: "浏览器测试大学",
      school_tier: "211/双一流",
      undergraduate_major: "软件工程",
      gpa: 82,
      gpa_scale: 100,
      target_degree_level: "授课型硕士",
      target_field: "计算机与数据",
      intake: "2027 S1",
      english_score: "IELTS 7.0，单项 6.5",
      coursework_summary: "高等数学、线性代数、数据结构、数据库、Python",
      experience_summary: "后端开发实习",
      career_goal: "AI 应用工程师",
      location_preferences: "悉尼优先",
      annual_budget_cny: 500000,
    },
  });
  expect(profile.ok()).toBe(true);
  const consent = await context.request.post(`${apiUrl}/me/advisor/consent`, { data: { accepted: false } });
  expect(consent.ok()).toBe(true);

  await page.route("**/me/advisor/threads/*/messages/stream", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: [
        "event: status",
        'data: {"message":"正在生成模拟回答","provider":"deterministic-fallback"}',
        "",
        "event: delta",
        'data: {"content":"这是一段尚未保存的回答"}',
        "",
      ].join("\n"),
    });
  });

  await page.goto("/");
  const navigation = page.getByRole("navigation", { name: "主要导航" });
  await expect(navigation.getByRole("button", { name: "AI 申请顾问" })).toBeVisible();
  await navigation.getByRole("button", { name: "AI 申请顾问" }).click();
  const advisorInput = page.getByPlaceholder(/我想把入学时间改到/);
  await expect(advisorInput).toBeEnabled();
  await expect(page.locator(".chat-message")).toHaveCount(1);

  await advisorInput.fill(message);
  await page.getByRole("button", { name: /^发送/ }).click();
  await expect(page.locator(".advisor-status")).toContainText("顾问连接在收到保存确认前中断，请重试");
  await expect(advisorInput).toHaveValue(message);
  await expect(advisorInput).toBeEnabled();
  await expect(page.locator(".chat-message")).toHaveCount(1);
  await expect(page.getByText("这是一段尚未保存的回答")).toHaveCount(0);

  const threadsResponse = await context.request.get(`${apiUrl}/me/advisor/threads`);
  const threads = await threadsResponse.json() as Array<{ messages: unknown[] }>;
  expect(threads).toHaveLength(1);
  expect(threads[0].messages).toHaveLength(1);
});

test("advisor reconciles a server-committed turn when state delivery is truncated", async ({ context, page }) => {
  const email = `e2e-sse-committed-${Date.now()}@offerpilot.test`;
  const message = "请确认服务端保存后不要重复提交";
  await registerAndLogin(context, email, "SSE 提交确认用户");

  const profile = await context.request.put(`${apiUrl}/me/profile`, {
    data: {
      current_education_level: "本科",
      undergraduate_school: "浏览器测试大学",
      school_tier: "211/双一流",
      undergraduate_major: "软件工程",
      gpa: 82,
      gpa_scale: 100,
      target_degree_level: "授课型硕士",
      target_field: "计算机与数据",
      intake: "2027 S1",
      english_score: "IELTS 7.0，单项 6.5",
      coursework_summary: "高等数学、线性代数、数据结构、数据库、Python",
      experience_summary: "后端开发实习",
      career_goal: "AI 应用工程师",
      location_preferences: "悉尼优先",
      annual_budget_cny: 500000,
    },
  });
  expect(profile.ok()).toBe(true);
  const consent = await context.request.post(`${apiUrl}/me/advisor/consent`, { data: { accepted: false } });
  expect(consent.ok()).toBe(true);

  await page.route("**/me/advisor/threads/*/messages/stream", async (route) => {
    const committedResponse = await route.fetch();
    expect(committedResponse.ok()).toBe(true);
    await committedResponse.body();
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: [
        "event: status",
        'data: {"message":"模拟保存确认丢失","provider":"deterministic-fallback"}',
        "",
      ].join("\n"),
    });
  });

  await page.goto("/");
  const navigation = page.getByRole("navigation", { name: "主要导航" });
  await expect(navigation.getByRole("button", { name: "AI 申请顾问" })).toBeVisible();
  await navigation.getByRole("button", { name: "AI 申请顾问" }).click();
  const advisorInput = page.getByPlaceholder(/我想把入学时间改到/);
  await expect(advisorInput).toBeEnabled();
  await advisorInput.fill(message);
  await page.getByRole("button", { name: /^发送/ }).click();

  await expect(page.locator(".advisor-status")).toContainText("回答已保存，已恢复最新会话");
  await expect(advisorInput).toHaveValue("");
  await expect(page.locator(".chat-message.user")).toHaveCount(1);
  await expect(page.locator(".chat-message.assistant")).toHaveCount(2);

  const threadsResponse = await context.request.get(`${apiUrl}/me/advisor/threads`);
  const threads = await threadsResponse.json() as Array<{ messages: Array<{ role: string; content: string }> }>;
  expect(threads).toHaveLength(1);
  expect(threads[0].messages).toHaveLength(3);
  expect(threads[0].messages.filter((item) => item.role === "user" && item.content === message)).toHaveLength(1);
});
