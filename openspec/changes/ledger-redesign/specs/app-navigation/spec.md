## ADDED Requirements

### Requirement: One route map for the whole product

The web application SHALL serve exactly these pages: `/`, `/assess`, `/assess/result`, `/portfolio`, `/roadmap`,
`/schools`, `/schools/[provider]`, `/programs`, `/programs/[code]`, `/advisor`, and `/me`. No route under
`/prototype` SHALL remain, and `/admin` SHALL NOT be served.

#### Scenario: A removed prototype route is not found

- **WHEN** a visitor opens `/prototype/schools`
- **THEN** the response is the not-found page, not a copy of the school library

#### Scenario: The back office is not served

- **WHEN** a visitor opens `/admin` or `/prototype/admin`
- **THEN** the response is the not-found page

### Requirement: Every page shares one shell that names the product

Every page SHALL render inside one shell whose top bar shows the product mark and the name 鱼跃彼岸 on the left,
the links 路线图, 选校, 学校库, 项目库, and 顾问, and a 我的背景 link on the right. The link for the current
page SHALL carry `aria-current="page"`. Below 640px wide the links SHALL fold into a menu opened by one button,
and the page SHALL NOT scroll sideways.

#### Scenario: The current page is marked

- **WHEN** the applicant is on `/schools/00008C`
- **THEN** the 学校库 link carries `aria-current="page"` and no other link does

#### Scenario: The navigation folds on a phone

- **WHEN** the page is 390px wide
- **THEN** the five links are hidden until the menu button is pressed, and the document is no wider than the
  viewport

### Requirement: A first visit and a return visit open different pages

`/` SHALL show a short introduction with two actions, 开始测评 (to `/assess`) and 先看学校 (to `/schools`), to a
visitor whose profile on the server has no completed assessment. A visitor whose profile has a completed
assessment SHALL be redirected from `/` to `/roadmap`. The decision SHALL come from the server-side profile, not
from a cookie or browser storage alone.

#### Scenario: A new visitor sees the introduction

- **WHEN** a visitor with no profile opens `/`
- **THEN** the page shows the introduction with links to `/assess` and `/schools`

#### Scenario: A returning applicant lands on the roadmap

- **WHEN** an applicant whose assessment is complete opens `/`
- **THEN** they are redirected to `/roadmap`

#### Scenario: Clearing browser storage does not lose the return

- **WHEN** an applicant with a completed assessment clears local and session storage and opens `/`
- **THEN** they are still redirected to `/roadmap`

### Requirement: No sales surface in this version

The interface SHALL NOT show a 联系顾问 button, a lead form, a consultation booking form, an 在线咨询 button on
school rows, or a WeChat QR placeholder.

#### Scenario: The school library has no consultation buttons

- **WHEN** the applicant opens `/schools`
- **THEN** no element in the page is labelled 在线咨询 or 联系顾问
