# Deploying LeapAshore

Operations guide for the production server, moved here from `note/handoff.md` on 2026-10-31. The current production state (Alembic revision, latest backup, data counts) is in `note/handoff.md`; per-task deploy results are in [measurements.md](measurements.md). Commands run on the server in `~/leapashore/deploy` unless they say otherwise; `...` stands for `sudo docker compose -f compose.prod.yaml`.

## First-time setup

On a fresh server with Docker, from the repository root:

```bash
cp deploy/.env.example deploy/.env   # set POSTGRES_PASSWORD and CHAT_API_KEY; the template lists every other setting
docker compose -f deploy/compose.prod.yaml up -d --build
```

The api container applies the Alembic migrations and runs the idempotent seeds at start-up (`api/Dockerfile`), which put the base catalogue and the roadmap in place. Then load the collected requirements with [Import collected data](#import-collected-data) and the advisor's snapshot text with [Ingest snapshots](#ingest-snapshots). Production starts in anonymous mode; see [Switch to sign-in mode](#switch-to-sign-in-mode).

## Server and routine deploy

- Server: `ubuntu@43.161.224.82`; SSH with `-i ~/.ssh/leapashore_prod -o IdentitiesOnly=yes` (that key is not in ssh-agent).
- SSH accepts keys only (since 2026-10-31): `/etc/ssh/sshd_config.d/01-hardening.conf` turns off password, keyboard-interactive and root logins. It sorts before `50-cloud-init.conf`, which still says `PasswordAuthentication yes`, and sshd keeps the first value it reads. fail2ban bans an address for 1 hour after 5 failures in 10 minutes (`/etc/fail2ban/jail.d/sshd.local`); `sudo fail2ban-client status sshd` lists bans, `sudo fail2ban-client set sshd unbanip <ip>` lifts one. If key login ever fails, use the VNC login in the Tencent Cloud console.
- Secrets live in the server's `~/leapashore/deploy/.env`, never in the repository.
- **Back up first:** `pg_dump` the production database to `~/db-backup-<date>.sql.gz` on the server before every deploy.
- **Sync the code:** locally `git archive origin/main`, then `rsync --delete` to the server's `~/leapashore/`, keeping `deploy/.env`, `deploy/*.bak-*` and `api/var/`. Then on the server `cd ~/leapashore/deploy && sudo docker compose -f compose.prod.yaml up -d --build`.
- **Schema changes:** the api container runs `alembic upgrade head` at start-up (`api/Dockerfile`), so back up → sync → `up -d --build` completes a migration; import data afterwards as below.
- **After a deploy, read-only checks only** (status codes, pages without errors). In anonymous mode `GET /api/profile` creates an anonymous subject: don't call it, or delete that subject by id afterwards. Never run the full walkthrough against production: its clean-up only deletes local data.
- **Caddy only:** after changing only the Caddy configuration, `... up -d --force-recreate --no-deps caddy`. Without `--force-recreate`, compose does not recreate the container for a changed Caddyfile, and the new file from rsync never reaches the old container's single-file mount. A deploy that changes the Caddyfile needs this step after `up -d --build` too.
- **The personal site:** `mortyyjt.site` and `www` are the owner's personal site, served by this server's Caddy from `/srv/mortyyjt.site` and uploaded by the personal site repository's GitHub Actions (its key is restricted to that folder with rrsync). The last two site blocks in `deploy/Caddyfile` and the `/srv/mortyyjt.site` mount in compose belong to it; do not remove them, and before a deploy check that `main`'s Caddyfile still has them, or the personal site goes down.

## Services

- **Redis:** compose has a `redis` service (advisor limits, reused by Celery), volume `redis-data`; api starts only when it is healthy. Today's site token usage: `... exec redis redis-cli --scan --pattern 'leapashore:tokens:site:*'`, then `GET` the key.
- **Collection queue** (from PR #50): production compose has `worker` (`--pool threads --concurrency 2`) and `beat` (exactly one). Snapshots live in the named volume `snapshots` (`/app/var/snapshots`), beat's schedule file in the volume `beat-data`. Beat re-collects pages not collected for 30 days at 04:07 Beijing time (default 200 pages and 1 yuan of model cost per day; `COLLECT_*` in `deploy/.env`) and runs the 90-day anonymous clean-up at 03:17 (it deletes only when `AUTH_ENABLED=true`, so step 6 of [Switch to sign-in mode](#switch-to-sign-in-mode) needs no cron). Progress: `... exec -T worker python -m app.collect.queue status --budget daily:$(TZ=Asia/Shanghai date +%F)`. To bring changes found in production into the repository: in the container `python -m app.collect.queue export --out /app/var/snapshots/_export`, `docker cp` it out, compare with the repository's files, review, commit, and import as below. The production image has no Chrome, so pages that need rendering are recorded as `deferred` there.
- **Conversation persistence** (from PR #56) deploys like any other change: the api container's `alembic upgrade head` creates the four checkpoint tables. A conversation waiting for confirmation at the moment of the deploy (still in memory then) loses its last step. Conversation count: `... exec -T db psql -U leapashore -d leapashore -c "select count(distinct thread_id) from checkpoints"` (database and user as in `deploy/.env`). Manual 90-day conversation clean-up: `... exec -T api python -m app.cleanup --conversations-only` (add `--apply` to delete).

## Import collected data

The way used since PR #52:

1. Unpack a tgz of the snapshot metadata into a separate folder in the api container (such as `/app/var/importmeta`).
2. Run a temporary script that calls `import_school(session, data, schools, root=<that folder>/snapshots)` for each file. Write the script to a file, `scp` it and `docker cp` it in; do not feed it to `docker compose exec` through ssh's standard input.
3. **Do not use `--prune`**: it would delete 3 earlier Curtin programs that have no CRICOS code.
4. Delete the tgz, the script and the unpacked folder afterwards.

The older way (PR #48), for reference: the local snapshot metadata JSON was copied into the api container temporarily and deleted right after the import (its `text_path` contains local paths; the importer does not read it): locally `cd api/var && tar czf <tmp>/snapmeta.tgz --exclude='_*' $(cd snapshots && find . -name '*.json' -not -name '_*' | sed 's#^#snapshots/#')`, `scp` to the server, `sudo docker cp` into `deploy-api-1:/app/var/`, `... exec -T api sh -c 'cd /app/var && tar xzf snapmeta.tgz && cd /app && python -m app.collect.importer'`, then `rm -rf /app/var/snapshots /app/var/snapmeta.tgz` in the container and delete the tgz on the server.

## Ingest snapshots

From P1 #5 (snapshot RAG); redo after large changes to collection files or snapshots. Production's `snapshots` volume started empty.

1. Locally, bundle the referenced snapshot texts and metadata (without `text_path`, which contains local paths): `cd api && .venv/bin/python -m app.collect.chunks bundle --out <tmp>/snaptext.tgz`. Only the `.txt` + `.json` referenced by collection files are bundled; pages the local queue collected but no file includes are left out (production's queue collects its own).
2. `scp` it to the server, `sudo docker cp snaptext.tgz deploy-worker-1:/tmp/`, then `... exec -T worker sh -c 'cd /app/var/snapshots && tar xzf /tmp/snaptext.tgz && rm /tmp/snaptext.tgz'` (files with the same name have the same content; they are named by sha256).
3. `... exec -T worker python -m app.collect.chunks ingest` (no `--prune`); record the output in [measurements.md](measurements.md). A second run should write 0 pages.
4. Delete the tgz on the server. Rollback: the three `snapshot_*` tables can be emptied (`TRUNCATE snapshot_pages CASCADE`); after a code rollback the advisor no longer reads them, and the tables stay (add-only schema).

## Move the database image to pgvector

From PR #58; follow this for any future rebuild of the database. Do not switch the image on the old volume: the old image is Alpine (musl) and the new one Debian (glibc); both call their locale `en_US.utf8` but sort text differently. Starting pgvector locally on the old data directory made `amcheck` report 7 of 53 btree indexes out of order (including `programs_pkey` and `sources_url_key`), and PostgreSQL gave no warning at start-up. Do not run a normal `up -d --build` either: the new volume is empty, so the api would create tables and seed an empty database in production. Order:

1. Back up: `... exec -T db pg_dump -U leapashore -d leapashore | gzip > ~/db-backup-<date>-pre-pgvector.sql.gz`.
2. Sync the code as above, but do not `up` yet.
3. Stop the services that write: `... stop api worker beat`.
4. Final dump (custom format) and digest: `... exec -T db pg_dump -U leapashore -d leapashore -Fc > ~/pgvector-move.dump`. The digest script (per table: row count + md5 of the sorted rows' md5s, independent of collation) is in PR #58's run log (`openspec/changes/hybrid-retrieval/tasks.md`); `docker cp` it into the container, run it with `psql -f` and save the output as `~/digest-old.txt`.
5. `... up -d db`: new image, new volume `pgdata`, initialised with `POSTGRES_INITDB_ARGS` (`C` collation). Wait for healthy.
6. `... exec -T db pg_restore -U leapashore -d leapashore --no-owner --exit-on-error < ~/pgvector-move.dump`, run the same digest script into `~/digest-new.txt`; `diff` must show no difference. Run `amcheck` once too (create the extension, check, drop the extension).
7. `... up -d --build`: the api's Alembic goes to `e3a9c5d17b42`. Then read-only checks.
8. Rollback (as it stood on 10-30; the `db-data` volume no longer exists, see below): put back the previous `compose.prod.yaml` and code (db on `postgres:16-alpine`, volume `db-data`) and `up -d --build`. The old volume was never written, so you return to the data as of step 3; writes to the new database after step 7 are lost. The new code cannot use the old volume (`CREATE EXTENSION vector` is not available in the Alpine image).

The old volume `deploy_db-data` from this move was deleted on 2026-10-31 (it stopped at 14:44 Beijing time on 10-30); roll back with the latest backup.

## Turn on vector retrieval

Any agent can do this once `EMBED_API_KEY` (SiliconFlow) exists:

1. Add `EMBED_API_KEY=…` to the server's `deploy/.env`, then `... up -d --force-recreate --no-deps api worker beat`.
2. `... exec -T api python -m app.agent.embeddings --dry-run` to see how much will be sent (locally on 10-30: 9,748 programs, 455,121 characters), then run it without `--dry-run`; the output has `tokens`, `cost_cny` and `seconds`, which go into [measurements.md](measurements.md). If it fails midway (for example on a 429), running it again continues.
3. **Change the privacy policy in the same deploy** (`web/app/privacy/page.tsx`): the advisor will send requirement questions' text to SiliconFlow for embeddings.
4. Locally: `export EMBED_API_KEY=…`, `cd api && .venv/bin/python -m app.agent.embeddings`, then run `python -m evals.run_advisor --split heldout --retrieval vector` and `--retrieval hybrid` once each (the held-out set is run once per ranking) and add the results to [measurements.md](measurements.md).
5. Snapshot chunks (from P1 #5): in production `... exec -T worker python -m app.agent.embeddings --chunks --dry-run`, then without `--dry-run` (locally 134,843 chunks, about 4,200 requests, about 550 MB of vectors; a failed run continues when run again). After doing the same locally, `evals.run_passages` can get a `--retrieval` option to compare `fts`/`vector`/`hybrid` (it currently follows the production setting).

## Switch to sign-in mode

Any agent can do steps 3–8 once the owner has done steps 1–2. The code sends over implicit TLS (`smtplib.SMTP_SSL`), so the port is 465 for any of the providers below.

The owner chose (2026-10-31) a personal mailbox's SMTP instead of Tencent Cloud SES: QQ Mail or Gmail. SES stays possible (see the end of this section).

1. Owner: turn on SMTP and get a password made for apps, never the account password.
   - **QQ Mail:** mail.qq.com → Settings → Account → "POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV service", turn on IMAP/SMTP and save the 16-character authorisation code (授权码). Server `smtp.qq.com`, port 465 with SSL (587 is the TLS port, which this code does not use); user name is the full address ([QQ Mail help](https://help.mail.qq.com/detail/108/1090/), checked 2026-10-31). Changing the QQ password voids the code.
   - **Gmail:** turn on 2-Step Verification, then create an app password at myaccount.google.com/apppasswords. Server `smtp.gmail.com`, 465 for SSL (587 is TLS); user name is the full address ([Google Workspace help, "Send email from a printer, scanner, or app"](https://knowledge.workspace.google.com/admin/gmail/send-email-from-a-printer-scanner-or-app), checked 2026-10-31). Changing the Google password revokes app passwords.
2. Owner: fill the server's `~/leapashore/deploy/.env` (template `deploy/.env.example`) **yourself**, not in a chat or the repository: `AUTH_ENABLED=true`, `MAIL_BACKEND=smtp`, `SMTP_HOST=smtp.qq.com` (or `smtp.gmail.com`), `SMTP_PORT=465`, `SMTP_USER=<the full mailbox address>`, `SMTP_PASSWORD=<the authorisation code or app password>`, `MAIL_FROM=鱼跃彼岸 <the same address as SMTP_USER>` (a personal mailbox may refuse or rewrite another sender address). `SMTP_HOST` must be set: its default is the SES host.
3. Check that the six variables are present without printing the password: `grep -E '^(AUTH_ENABLED|MAIL_BACKEND|SMTP_HOST|SMTP_PORT|SMTP_USER|MAIL_FROM)=' ~/leapashore/deploy/.env` and `grep -c '^SMTP_PASSWORD=.' ~/leapashore/deploy/.env` (1).
4. Back up the database as for a deploy (sign-in mode starts writing accounts and sessions).
5. `... up -d --force-recreate --no-deps api`; the start-up succeeded only if `docker compose logs api` does not contain `AUTH_ENABLED=true in production needs a real mail backend`. The owner signs in on the site with their own email once and confirms the mail arrives (check the spam folder); a failed send shows in `docker compose logs api` as `login code mail to … failed: <exception class>`.
6. The 90-day clean-up cron (`crontab -e`, server local time): `17 3 * * * cd ~/leapashore/deploy && sudo docker compose -f compose.prod.yaml exec -T api python -m app.cleanup --apply >> ~/cleanup.log 2>&1`. Run it once by hand without `--apply` first to see the report. (Since PR #50 beat runs this clean-up at 03:17 in sign-in mode, so this cron is no longer needed.)
7. Rollback: remove `AUTH_ENABLED=true` from `.env` and recreate the api; that returns to anonymous mode, and the tables can stay.

8. Make the owner an admin (P2 #3): the owner signs in once on the site with their email (the account must exist), then `... exec -T api python -m app.roles grant <the owner's sign-in email>`, and `... exec -T api python -m app.roles list` to confirm. Ask the owner for the email; never write it into the repository. Only then does `https://leapashore.mortyyjt.site/admin` open (verification and the knowledge-gap queue). Revoke: `python -m app.roles revoke <email>`.

Tencent Cloud SES instead of a personal mailbox (the earlier plan): enable SES (the server is in Hong Kong, so `smtp.qcloudmail.com:465`; `gz-smtp.qcloudmail.com` if opened in Guangzhou), add a sender domain such as `mail.mortyyjt.site` and its SPF, DKIM and DMARC records in DNSPod (values from the SES console's verification page), create `noreply@mail.mortyyjt.site` with an SMTP password, then use those values in step 2.

## Pitfalls on the server

- In a `while read` loop, `docker compose exec -T` needs `< /dev/null`, otherwise exec swallows the loop's input (on 10-30 the school merge first ran only the first group).
- Do not run a temporary script in the api or worker container as `python /tmp/x.py`: the script's folder comes first on the search path and `app` then resolves to the copy installed into site-packages by `pip install .` (on 10-30 this gave `No module named 'app.agent'`). Use `python -c` or `python -m` with working directory `/app`.
- Keep `KNOWLEDGE_GAP_HASH_KEY` in `deploy/.env` unchanged: with a new key, old gap reports can no longer be deleted when their account is deleted, only after 90 days.
