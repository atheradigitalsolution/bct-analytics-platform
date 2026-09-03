import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

/**
 * Absence tests.
 *
 * Every claim in the brief that takes the form "this application never does X" is asserted here by
 * looking for X in the source and the dependency tree, rather than by describing the intention in a
 * comment. An absence that nothing checks is an absence that lasts until the next commit.
 *
 * How these were made to go red: `pg` was temporarily added to `package.json` (the driver test
 * failed naming it), a `const q = "SELECT value FROM marts.mart_revenue_daily"` line was added to
 * `src/lib/semantic.ts` (the SQL and the schema tests both failed naming the file), and a `tenant`
 * field was added to `QuerySpec` (the tenant-argument test failed). All three were reverted.
 */

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const src = join(root, "src");

function sourceFiles(dir: string = src): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      out.push(...sourceFiles(full));
    } else if (/\.(ts|tsx|mjs|js)$/.test(entry)) {
      out.push(full);
    }
  }
  return out;
}

/**
 * Strip comments before scanning.
 *
 * Without this the scans match their own prose: the export route explains that no unmasking path
 * exists, and `config.ts` explains that nothing is prefixed with the public env prefix. Both were
 * reported as offenders on the first run. That is a false positive, and silencing it by rewording
 * the comment would be worse than fixing it properly, because the next person writes the same
 * sentence and the test fires again.
 *
 * A stripper is itself somewhere a test can go vacuously green: one that returned an empty string
 * would make every scan below pass forever. The first test exists to stop exactly that.
 */
function stripComments(text: string): string {
  const withoutBlocks = text.replace(/\/\*[\s\S]*?\*\//g, " ");
  const lines = withoutBlocks.split("\n");
  return lines.map((line) => line.replace(/(^|[^:"'`])\/\/.*$/, "$1")).join("\n");
}

test("the comment stripper leaves code behind", () => {
  const sample = [
    "/** a doc comment mentioning SELECT x FROM y and unmask */",
    "const keep = 1; // a trailing comment mentioning unmask",
    "// a whole-line comment mentioning SELECT x FROM y",
    'const url = "https://example.invalid/path";',
  ].join("\n");
  const stripped = stripComments(sample);
  assert.match(stripped, /const keep = 1;/, "the stripper must not remove code");
  assert.match(stripped, /https:\/\/example\.invalid\/path/, "a URL is not a comment");
  assert.equal(/unmask/i.test(stripped), false, "comment prose must be gone");
  assert.equal(/SELECT/i.test(stripped), false);
});

test("the source scan actually reads files", () => {
  const files = sourceFiles();
  assert.ok(files.length > 10, "found only " + files.length + " source files; the scan is not looking");
  assert.ok(
    files.some((file) => file.endsWith("semantic.ts")),
    "the API client must be in the scanned set",
  );
});

const DATABASE_DRIVERS = [
  "pg",
  "pg-promise",
  "postgres",
  "mysql",
  "mysql2",
  "sqlite3",
  "better-sqlite3",
  "mongodb",
  "mongoose",
  "knex",
  "prisma",
  "@prisma/client",
  "drizzle-orm",
  "typeorm",
  "sequelize",
  "oracledb",
  "mssql",
  "tedious",
  "ioredis",
  "redis",
];

/**
 * SATU-SATUNYA berkas yang boleh menyentuh database secara langsung.
 *
 * Invarian aslinya adalah "aplikasi ini tidak punya jalur database sama sekali", dan itu ditulis
 * ketika aplikasi ini hanya berisi dasbor. Permukaan penagihan klien (2026-09-04) memerlukan
 * jalur langsung ke `athera_admin`, karena faktur ATHERA kepada kliennya tidak pernah ada di
 * mart: CDC memberi makan dari database KLIEN, bukan dari database kontrol.
 *
 * YANG DIPERTAHANKAN — dan justru diperketat. Maksud invarian itu bukan "tidak ada driver";
 * maksudnya adalah JALUR ANALITIK tidak boleh punya jalan pintas ke gudang data. Karena itu
 * pengecualian di bawah dibatasi pada SATU berkas dengan nama tepat, bukan pada seluruh aplikasi.
 * Menambah `pg` ke `lib/semantic.ts` tetap merah. Menambah pool kedua di halaman mana pun tetap
 * merah. Yang dulu dijaga oleh ketiadaan dependensi kini dijaga oleh daftar berisi satu nama.
 *
 * Cara membuatnya merah, diuji: mengganti `DIRECT_DB_FILE` ke berkas lain membuat uji importir
 * gagal sambil menyebut `src/lib/billing.ts`; menambahkan `import { Pool } from "pg"` ke
 * `src/lib/semantic.ts` membuatnya gagal sambil menyebut berkas itu.
 */
const DIRECT_DB_FILE = "src/lib/billing.ts";

test("the only database driver declared is the one the billing surface needs", () => {
  const parsed: unknown = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
  const record = parsed as {
    dependencies?: Record<string, string>;
    devDependencies?: Record<string, string>;
  };
  const declared = Object.keys({ ...record.dependencies, ...record.devDependencies });
  assert.ok(declared.length > 0, "no dependencies parsed; the check would pass vacuously");
  const found = declared.filter((name) => DATABASE_DRIVERS.includes(name)).sort();
  assert.deepEqual(
    found,
    ["pg"],
    "only `pg` may be declared, and only for the billing surface; any other driver is a second path",
  );
});

test("only the billing surface imports the database driver", () => {
  const offenders: string[] = [];
  for (const file of sourceFiles()) {
    const rel = relative(root, file);
    if (rel === DIRECT_DB_FILE) continue;
    const text = stripComments(readFileSync(file, "utf8"));
    if (/from\s+["\']pg["\']|require\(\s*["\']pg["\']\s*\)/.test(text)) offenders.push(rel);
  }
  assert.deepEqual(
    offenders,
    [],
    "the analytics path reaches the warehouse only through the semantic API",
  );
});

test("the billing surface is the file it claims to be", () => {
  // Menjaga uji di atas tidak menjadi hijau-hampa kalau berkasnya dipindah atau dihapus.
  const text = readFileSync(join(root, DIRECT_DB_FILE), "utf8");
  assert.ok(/from "pg"/.test(text), `${DIRECT_DB_FILE} no longer imports pg; the carve-out is stale`);
});

test("no source file outside the billing surface contains SQL", () => {
  const offenders: string[] = [];
  for (const file of sourceFiles()) {
    if (relative(root, file) === DIRECT_DB_FILE) continue;
    const text = stripComments(readFileSync(file, "utf8"));
    if (/\bSELECT\b[\s\S]{0,120}\bFROM\b/i.test(text)) offenders.push(relative(root, file));
    if (
      /\b(INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|CREATE\s+TABLE|DROP\s+TABLE)\b/i.test(text)
    ) {
      offenders.push(relative(root, file));
    }
  }
  assert.deepEqual(offenders, [], "these files contain SQL; the semantic layer owns every query");
});

test("no source file names a warehouse schema or mart in a string", () => {
  const offenders: string[] = [];
  for (const file of sourceFiles()) {
    const text = stripComments(readFileSync(file, "utf8"));
    if (/["\'`]marts\./.test(text)) offenders.push(relative(root, file));
  }
  assert.deepEqual(offenders, []);
});

test("the billing surface never reaches into the warehouse", () => {
  // Pengecualian SQL di atas berlaku untuk satu berkas; ia TIDAK berlaku untuk gudang data.
  // Kalau suatu hari seseorang menempelkan kueri mart ke sini karena "sudah ada koneksinya",
  // itulah persis jalan pintas yang invarian aslinya ada untuk mencegah.
  const text = stripComments(readFileSync(join(root, DIRECT_DB_FILE), "utf8"));
  for (const schema of ["marts.", "staging.", "raw.", "warehouse."]) {
    assert.equal(
      text.includes(schema),
      false,
      `${DIRECT_DB_FILE} names ${schema}; the warehouse is reached through the semantic API only`,
    );
  }
});

test("no unmasking path exists anywhere in the source", () => {
  const offenders: string[] = [];
  for (const file of sourceFiles()) {
    const text = stripComments(readFileSync(file, "utf8"));
    if (/\b(unmask|unhash|dehash|decrypt|deanonymi|reIdentif|reverseMask)/i.test(text)) {
      offenders.push(relative(root, file));
    }
  }
  assert.deepEqual(
    offenders,
    [],
    "data arrives already masked; an unmasking symbol here would be a path that must not exist",
  );
});

test("the semantic client takes no tenant argument", () => {
  const text = readFileSync(join(src, "lib", "semantic.ts"), "utf8");
  const spec = /export interface QuerySpec \{([\s\S]*?)\}/.exec(text);
  assert.notEqual(spec, null, "QuerySpec must exist");
  assert.equal(
    /tenant/i.test(spec?.[1] ?? ""),
    false,
    "QuerySpec must have no tenant field: there must be no argument through which scope can travel",
  );
  assert.match(
    text,
    /export async function query\(spec: QuerySpec\)/,
    "query() must take exactly the spec and nothing else",
  );
});

test("no publicly-prefixed environment variable is defined anywhere", () => {
  const prefix = "NEXT_" + "PUBLIC_";
  const offenders: string[] = [];
  for (const file of sourceFiles()) {
    const text = stripComments(readFileSync(file, "utf8"));
    if (text.includes(prefix)) offenders.push(relative(root, file));
  }
  assert.deepEqual(
    offenders,
    [],
    "a publicly-prefixed variable is inlined into the client bundle; no server value may take that route",
  );
});

test("no client component imports a server-only module", () => {
  const offenders: string[] = [];
  let clientComponents = 0;
  for (const file of sourceFiles()) {
    const text = readFileSync(file, "utf8");
    if (!/^["']use client["']/m.test(text)) continue;
    clientComponents += 1;
    if (/from "@\/lib\/(semantic|session|config|ou|panels|view)"/.test(text)) {
      offenders.push(relative(root, file));
    }
  }
  assert.ok(clientComponents > 0, "no client components found; the check would pass vacuously");
  assert.deepEqual(
    offenders,
    [],
    "a client component importing the API client would put the bearer token in the browser bundle",
  );
});

test("the tenant guard compares the URL segment against the verified session", () => {
  const text = readFileSync(join(src, "middleware.ts"), "utf8");
  assert.match(text, /match\[1\] !== session\.tenant_id/);
  assert.match(text, /TENANT_SCOPE_VIOLATION/, "the refusal body must be the contract 02 constant");
  assert.match(text, /status: 403/, "the refusal must be a 403");
});

test("the contract 02 refusal body is verbatim", () => {
  const text = readFileSync(join(src, "lib", "types.ts"), "utf8");
  assert.match(text, /error: "tenant_scope_violation"/);
  assert.match(text, /detail: "Session is not scoped to the requested tenant\."/);
});

test("freshness is never derived from a clock", () => {
  const freshness = readFileSync(join(src, "components", "Freshness.tsx"), "utf8");
  assert.equal(
    /Date\.now\(\)|new Date\(\)/.test(stripComments(freshness)),
    false,
    "the freshness component must not read a clock; staleness is meta.is_stale",
  );
  const format = stripComments(readFileSync(join(src, "lib", "format.ts"), "utf8"));
  assert.equal(
    /Date\.now\(\)/.test(format),
    false,
    "formatRefreshedAt must render the pipeline instant, not compare it to now",
  );
});
