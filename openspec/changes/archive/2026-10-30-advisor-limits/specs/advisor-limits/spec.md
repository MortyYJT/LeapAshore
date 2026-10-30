## ADDED Requirements

### Requirement: Advisor chats are rate limited by subject and by IP

`POST /api/advisor/chat` SHALL be refused with 429 when the subject or the client IP has used up any
of its sliding windows. A refused request SHALL NOT count against any window.

#### Scenario: Switching account does not escape the IP limit

- **WHEN** one IP has used up its window and a different account sends from the same IP
- **THEN** the request is refused with 429

#### Scenario: A forged forwarding header has no effect

- **WHEN** a client that is not the trusted proxy sends `X-Forwarded-For` with a fresh address
- **THEN** the limit is still applied to the connection's own address

### Requirement: Daily token caps

The advisor SHALL refuse a chat or confirm with 429 when the subject, the IP or the whole site has
reached its daily token cap. Usage SHALL be counted from the model's reported tokens.

#### Scenario: Site cap reached

- **WHEN** the site's tokens today have reached the site cap
- **THEN** every subject is refused with a message that says the site's quota is used up

#### Scenario: A client that hangs up is still charged

- **WHEN** a client disconnects before the model has reported the turn's usage
- **THEN** the turn still runs to the end and its usage is counted

#### Scenario: Turns admitted together see each other

- **WHEN** several turns are admitted before any of them has reported usage
- **THEN** each holds a reservation on the counters, so the caps refuse once the reservations reach them

### Requirement: Limits fail closed

The advisor SHALL return 503 and call no model when the limit store cannot be reached.

#### Scenario: The admission ran but its reply was lost

- **WHEN** the admission script runs in Redis but its reply times out
- **THEN** the advisor returns 503, and the reservation and the window entry are given back

### Requirement: Every model call has an output limit

Every chat model request SHALL carry `max_tokens` in its body.

#### Scenario: The cap is in the request body

- **WHEN** the advisor builds a chat model request without an explicit limit
- **THEN** the request body carries `max_tokens` set to `CHAT_MAX_TOKENS`, not `max_completion_tokens`
