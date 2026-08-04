import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { chmod, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const repositoryRoot = fileURLToPath(new URL("..", import.meta.url));
const restoreScript = fileURLToPath(new URL("../deploy/restore-smoke.sh", import.meta.url));

const fakePostgresCommand = `#!/bin/sh
set -eu

command_name="$(basename "$0")"
printf '%s %s\\n' "$command_name" "$*" >> "$FAKE_COMMAND_LOG"

case "$command_name" in
    psql)
        case "$*" in
            *"SELECT current_database()"*)
                printf '%s\\n' 'offerpilot_test'
                ;;
            *"COPY ("*"SELECT to_jsonb(row_value)"*)
                row='{"stable":true}'
                case "$*" in
                    *"FROM users AS row_value"*)
                        row='{"display_name":"Restore Smoke","id":"restore-smoke-user"}'
                        case "$*" in
                            *op_restore_*)
                                if [ "\${FAKE_RESTORE_CONTENT_MISMATCH:-0}" = "1" ]; then
                                    row='{"display_name":"Tampered","id":"restore-smoke-user"}'
                                fi
                                ;;
                        esac
                        ;;
                esac
                printf '%s\\n' "$row"
                ;;
            *--set=alembic_digest=*)
                manifest_sql="$(cat)"
                printf '%s\\n' "$manifest_sql" >> "$FAKE_COMMAND_LOG"
                alembic_digest=''
                auth_tokens_digest=''
                entities_digest=''
                feedback_digest=''
                program_source_versions_digest=''
                sessions_digest=''
                users_digest=''
                for argument in "$@"; do
                    case "$argument" in
                        --set=alembic_digest=*) alembic_digest="\${argument#--set=alembic_digest=}" ;;
                        --set=auth_tokens_digest=*) auth_tokens_digest="\${argument#--set=auth_tokens_digest=}" ;;
                        --set=entities_digest=*) entities_digest="\${argument#--set=entities_digest=}" ;;
                        --set=feedback_digest=*) feedback_digest="\${argument#--set=feedback_digest=}" ;;
                        --set=program_source_versions_digest=*) program_source_versions_digest="\${argument#--set=program_source_versions_digest=}" ;;
                        --set=sessions_digest=*) sessions_digest="\${argument#--set=sessions_digest=}" ;;
                        --set=users_digest=*) users_digest="\${argument#--set=users_digest=}" ;;
                    esac
                done
                users_count=1
                case "$*" in
                    *op_restore_*)
                        if [ "\${FAKE_RESTORE_PRIMARY_KEY_MISMATCH:-0}" = "1" ]; then
                            users_count=2
                        fi
                        ;;
                esac
                printf '%s\\n' \\
                    "alembic_version|1|[\\"0003_program_source_versions\\"]|$alembic_digest" \\
                    "auth_tokens|1|[\\"restore-smoke-auth-token\\"]|$auth_tokens_digest" \\
                    "entities|1|[[\\"restore-smoke-user\\", \\"restore_smoke\\", \\"restore-smoke-entity\\"]]|$entities_digest" \\
                    "feedback|1|[\\"restore-smoke-feedback\\"]|$feedback_digest" \\
                    "program_source_versions|1|[\\"restore-smoke-source-version\\"]|$program_source_versions_digest" \\
                    "sessions|1|[\\"restore-smoke-session\\"]|$sessions_digest" \\
                    "users|$users_count|[\\"restore-smoke-user\\"]|$users_digest"
                ;;
        esac
        ;;
    pg_dump)
        backup_path=''
        for argument in "$@"; do
            case "$argument" in
                --file=*) backup_path="\${argument#--file=}" ;;
            esac
        done
        [ -n "$backup_path" ]
        if [ "\${FAKE_EMPTY_DUMP:-0}" = "1" ]; then
            : > "$backup_path"
        else
            printf '%s\\n' 'fake custom dump' > "$backup_path"
        fi
        ;;
    pg_restore|createdb|dropdb)
        ;;
    *)
        echo "unexpected fake command: $command_name" >&2
        exit 90
        ;;
esac
`;

async function createFakePostgresBin(root) {
  const binDirectory = join(root, "bin");
  const commandLog = join(root, "commands.log");
  await mkdir(binDirectory);
  await writeFile(commandLog, "", "utf8");
  await Promise.all(
    ["psql", "pg_dump", "pg_restore", "createdb", "dropdb"].map(async (command) => {
      const commandPath = join(binDirectory, command);
      await writeFile(commandPath, fakePostgresCommand, { encoding: "utf8", mode: 0o755 });
      await chmod(commandPath, 0o755);
    }),
  );
  return { binDirectory, commandLog };
}

function runRestoreSmoke(root, binDirectory, commandLog, options = {}) {
  const {
    primaryKeyMismatch = false,
    contentMismatch = false,
    emptyDump = false,
  } = options;
  return new Promise((resolve, reject) => {
    const child = spawn("/bin/sh", [restoreScript], {
      cwd: repositoryRoot,
      env: {
        ...process.env,
        PATH: `${binDirectory}:${process.env.PATH ?? ""}`,
        DATABASE_URL: "postgresql://offerpilot:test@localhost:5432/offerpilot_test",
        PYTHON_BIN: process.env.PYTHON_BIN ?? "python3",
        RESTORE_SMOKE_CONFIRM_EPHEMERAL: "1",
        FAKE_COMMAND_LOG: commandLog,
        FAKE_RESTORE_PRIMARY_KEY_MISMATCH: primaryKeyMismatch ? "1" : "0",
        FAKE_RESTORE_CONTENT_MISMATCH: contentMismatch ? "1" : "0",
        FAKE_EMPTY_DUMP: emptyDump ? "1" : "0",
        TMPDIR: root,
      },
    });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.on("error", reject);
    child.on("close", (code) => resolve({ code, stdout, stderr }));
  });
}

test("restore smoke dumps, restores, compares manifests, and drops the temporary database", async () => {
  const root = await mkdtemp(join(tmpdir(), "offerpilot-restore-test-"));
  try {
    const { binDirectory, commandLog } = await createFakePostgresBin(root);
    const result = await runRestoreSmoke(root, binDirectory, commandLog);
    const log = await readFile(commandLog, "utf8");

    assert.equal(result.code, 0, result.stderr);
    assert.match(result.stdout, /restore_smoke_passed/);
    assert.match(result.stdout, /row_digest=sha256/);
    assert.match(result.stdout, /dump_sha256=[a-f0-9]{64}/);
    for (const command of ["pg_dump ", "createdb ", "pg_restore ", "dropdb "]) {
      assert.match(log, new RegExp(command));
    }
    assert.equal((log.match(/psql /g) ?? []).length, 18);
    assert.match(log, /SELECT 'alembic_version'::text AS relation_name/);
    assert.match(log, /SELECT to_jsonb\(row_value\)[\s\S]*FROM users AS row_value/);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("restore smoke fails on a primary-key manifest mismatch and still cleans up", async () => {
  const root = await mkdtemp(join(tmpdir(), "offerpilot-restore-test-"));
  try {
    const { binDirectory, commandLog } = await createFakePostgresBin(root);
    const result = await runRestoreSmoke(root, binDirectory, commandLog, { primaryKeyMismatch: true });
    const log = await readFile(commandLog, "utf8");

    assert.equal(result.code, 1);
    assert.match(result.stderr, /restore_smoke_manifest_mismatch/);
    assert.match(log, /dropdb /);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("restore smoke fails when full row content changes without a key change", async () => {
  const root = await mkdtemp(join(tmpdir(), "offerpilot-restore-test-"));
  try {
    const { binDirectory, commandLog } = await createFakePostgresBin(root);
    const result = await runRestoreSmoke(root, binDirectory, commandLog, { contentMismatch: true });
    const log = await readFile(commandLog, "utf8");

    assert.equal(result.code, 1);
    assert.match(result.stderr, /restore_smoke_manifest_mismatch/);
    assert.match(log, /dropdb /);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("restore smoke rejects an empty dump before creating the restore database", async () => {
  const root = await mkdtemp(join(tmpdir(), "offerpilot-restore-test-"));
  try {
    const { binDirectory, commandLog } = await createFakePostgresBin(root);
    const result = await runRestoreSmoke(root, binDirectory, commandLog, { emptyDump: true });
    const log = await readFile(commandLog, "utf8");

    assert.equal(result.code, 1);
    assert.match(result.stderr, /restore_smoke_empty_dump/);
    assert.doesNotMatch(log, /createdb |pg_restore |dropdb /);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("CI runs the guarded restore smoke and shellchecks its implementation", async () => {
  const scriptSource = await readFile(restoreScript, "utf8");
  const workflowSource = await readFile(new URL("../.github/workflows/ci.yml", import.meta.url), "utf8");

  for (const marker of [
    "RESTORE_SMOKE_CONFIRM_EPHEMERAL",
    "pg_dump",
    "pg_restore",
    "diff -u",
    "alembic_version",
    "program_source_versions",
    "row_digest",
    "sha256_file",
    "restore_smoke_empty_dump",
  ]) {
    assert.match(scriptSource, new RegExp(marker));
  }
  assert.match(workflowSource, /RESTORE_SMOKE_CONFIRM_EPHEMERAL=1 \.\.\/deploy\/restore-smoke\.sh/);
  assert.match(workflowSource, /shellcheck .*deploy\/restore-smoke\.sh/);
});
