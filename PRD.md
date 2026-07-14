# 留学申请规划 Agent — MVP PRD

版本：v0.1  
日期：2026-07-14  
目标：当天完成一个可演示的网站版本

## 1. 产品概述

面向计划申请澳大利亚硕士的学生。用户注册或登录后填写个人背景与申请偏好，系统基于澳洲八大院校的项目数据，生成“冲刺 / 匹配 / 保底”推荐，并解释推荐原因、风险和下一步行动。

核心价值不是简单展示学校，而是把用户背景转化为可执行的申请建议。

## 2. MVP 目标

- 完成邮箱注册、登录和退出登录。
- 用户能够填写并保存一份结构化申请背景。
- 系统能够展示澳洲八大院校，并根据背景生成推荐结果。
- 每项推荐必须展示可理解的匹配理由和风险提示。
- 网站在桌面端和手机端均可完成核心流程。

### 本期不做

- 不承诺或预测精确录取概率。
- 不开放全球院校与本科、博士申请。
- 不做完整文书生成、签证办理、职业规划和付费系统。
- 不在 Demo 阶段实现自动爬取与自动更新学校官网。
- 不在 Demo 阶段处理成绩单、护照等文件解析；“上传背景”指填写结构化表单。

## 3. 目标用户

- 计划申请澳大利亚授课型硕士的中国学生。
- 对选校档位、申请门槛和准备顺序缺乏清晰判断。
- 希望快速获得第一版方案，再决定是否进行深入咨询。

## 4. 核心用户流程

1. 用户进入首页，点击“开始规划”。
2. 用户使用邮箱注册或登录。
3. 用户填写背景资料与申请偏好。
4. 系统检查必填项并生成推荐。
5. 用户查看冲刺 / 匹配 / 保底结果及推荐理由。
6. 用户进入学校详情，查看简介、匹配分析和注意事项。
7. 用户返回个人中心修改背景并重新生成方案。

## 5. 页面范围

### 5.1 首页 `/`

- 产品定位与价值说明。
- “开始规划”主按钮。
- 简要说明三步流程：填写背景、智能匹配、获得行动建议。
- 展示当前覆盖范围：澳洲八大、硕士申请、Demo 数据。

### 5.2 登录与注册 `/login`

- 邮箱 + 密码注册与登录。
- 登录失败、加载中和成功状态。
- Demo 优先使用邮箱登录；Google 登录后续增加。

### 5.3 背景录入 `/profile`

必填字段：

- 本科学校名称。
- 院校背景类型：985 / 211 / 双一流 / 海外院校 / 双非 / 其他。
- 本科专业。
- GPA 数值及满分制。
- 目标专业方向。
- 计划入学年份。

选填字段：

- 雅思 / 托福成绩。
- GRE / GMAT 成绩。
- 实习、工作、科研年限。
- 预算范围。
- 偏好城市。
- 个人经历补充说明。

交互要求：分步骤填写、显示进度、支持保存和返回修改。

### 5.4 推荐结果 `/recommendations`

- 顶部展示用户背景摘要。
- 分为冲刺、匹配、保底三个分组。
- 推荐卡片展示：学校、城市、推荐档位、匹配分、主要理由、主要风险。
- 支持按城市和档位筛选。
- 提供“修改背景”和“重新生成”入口。

### 5.5 学校详情 `/universities/[slug]`

- 学校名称、城市、官网和简要介绍。
- 与当前用户背景的匹配解释。
- 通用学术与语言要求说明。
- 数据来源与最近核验日期。
- 明确提示：最终要求以具体项目官网为准。

### 5.6 个人中心 `/dashboard`

- 背景资料完成度。
- 最近一次推荐结果。
- 修改背景、查看推荐和退出登录。

## 6. 澳洲八大数据范围

- Australian National University
- University of Melbourne
- University of Sydney
- University of New South Wales
- University of Queensland
- Monash University
- University of Western Australia
- University of Adelaide / Adelaide University（展示名称与当前官方口径在录入数据时核验）

Demo 首先维护学校级信息与少量代表性专业方向。正式版本必须升级到“具体项目级”数据，因为录取要求通常因学院和项目而异。

每条数据至少包含：

- 学校名称、Slug、城市、简介、官网。
- 支持的专业方向标签。
- 背景评估规则。
- 通用 GPA 与语言要求说明。
- 信息来源 URL。
- 最近核验时间。

## 7. 推荐逻辑 v0

Demo 使用透明的规则引擎，不直接让大模型决定录取档位。

建议维度：

- 学术成绩：45%。
- 本科院校背景：20%。
- 专业相关性：20%。
- 语言与标化准备度：10%。
- 实习 / 科研经历：5%。

输出档位：

- 冲刺：基础门槛大致满足，但竞争力存在明显差距。
- 匹配：主要条件基本满足，仍需结合具体项目判断。
- 保底：当前背景相对要求具有一定余量。
- 暂不推荐：存在明确硬性门槛缺口。

所有结果必须返回：档位、分项得分、2—3 条理由、1—2 条风险和下一步建议。界面使用“匹配分”，避免写成“录取概率”。

## 8. 技术方案

### 前端

- Next.js App Router + TypeScript。
- Tailwind CSS + shadcn/ui。
- 表单：React Hook Form + Zod。
- 请求与缓存：原生 `fetch`；复杂交互增加 TanStack Query。

选择理由：页面开发快、路由和 SEO 能力完整、组件生态成熟，适合今天快速产出，也能支撑后续扩展。

### 后端

- Python 3.12+。
- FastAPI + Pydantic v2。
- SQLAlchemy 2 + Alembic。
- 推荐逻辑作为独立 service，避免写进路由。
- 测试使用 pytest。

选择理由：保留 Python 作为未来数据处理、推荐算法和 AI 能力的主语言；FastAPI 自动生成 OpenAPI 文档，方便前后端协作。

### 数据库与登录

- Supabase PostgreSQL。
- Supabase Auth，Demo 先支持邮箱密码。
- 前端获得用户 JWT；调用 FastAPI 时通过 `Authorization: Bearer <token>` 传递。
- FastAPI 服务端验证 JWT，并使用用户 ID 做数据归属校验。
- 表级开启 Row Level Security；服务端密钥不得进入浏览器。

选择理由：一个平台同时解决 PostgreSQL、用户账号与后续对象存储，今天可以少搭建一套账号基础设施。

### 部署建议

- 前端：Sites 或 Vercel。
- FastAPI：Railway、Render 或 Fly.io 中选择一个；Demo 优先选择团队已有账号的平台。
- 数据库与 Auth：Supabase 托管。
- 正式环境分别配置前端、后端和数据库密钥，限制 CORS 来源。

### 仓库结构

```text
留学agent/
├── web/                 # Next.js 前端
├── api/                 # FastAPI 后端
│   ├── app/
│   │   ├── api/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── services/
│   │   └── main.py
│   └── tests/
├── data/                # 澳洲八大种子数据与来源记录
└── PRD.md
```

## 9. MVP 数据模型

### profiles

- id
- user_id
- undergraduate_school
- school_tier
- undergraduate_major
- gpa
- gpa_scale
- language_test_type
- language_score
- target_field
- intake_year
- budget_aud
- preferred_cities
- experience_summary
- created_at / updated_at

### universities

- id
- name
- slug
- city
- description
- official_url
- source_url
- verified_at

### university_rules

- id
- university_id
- target_field
- minimum_gpa_normalized
- preferred_school_tiers
- language_guidance
- rule_config JSONB
- source_url
- verified_at

### recommendation_runs

- id
- user_id
- profile_snapshot JSONB
- result JSONB
- algorithm_version
- created_at

## 10. API 草案

- `GET /health`：健康检查。
- `GET /me/profile`：读取当前用户背景。
- `PUT /me/profile`：创建或更新背景。
- `GET /universities`：获取澳洲八大列表。
- `GET /universities/{slug}`：获取学校详情。
- `POST /recommendations`：根据当前背景生成推荐。
- `GET /recommendations/latest`：获取最近一次结果。

## 11. Demo 验收标准

- 新用户能完成注册、登录和退出。
- 登录用户能完成并保存背景表单。
- 提交后能看到至少 8 所学校的分档推荐。
- 每所学校都有匹配理由、风险和来源提示。
- 未登录用户不能访问个人背景与推荐结果。
- 手机宽度下核心操作可完成。
- 关键接口出现错误时，页面有明确提示和重试入口。

## 12. 今日实施顺序

1. 初始化前端与后端工程，确定基础视觉风格。
2. 完成首页、登录页和应用导航。
3. 完成背景表单与本地校验。
4. 写入澳洲八大种子数据。
5. 实现规则推荐接口与结果页。
6. 接入账号和持久化；如果云端配置延迟，先用 Demo 账号与内存种子数据打通完整流程。
7. 完成构建、移动端检查并发布演示地址。

## 13. 后续版本

- 从学校级推荐升级为具体项目级推荐。
- 后台数据维护、来源审核和过期提醒。
- 成绩单与简历解析。
- 申请时间线、材料清单和截止日期提醒。
- 文书素材访谈与材料版本管理。
- 职业目标到课程、项目和岗位能力的映射。

