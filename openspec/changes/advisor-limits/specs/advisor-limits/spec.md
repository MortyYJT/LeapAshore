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

### Requirement: Limits fail closed

The advisor SHALL return 503 and call no model when the limit store cannot be reached.

### Requirement: Every model call has an output limit

Every chat model request SHALL carry `max_tokens` in its body.
