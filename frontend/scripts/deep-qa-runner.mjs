import http from "node:http";
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const PORT = Number(process.env.QA_RUNNER_PORT || 3999);

/** Prefer Docker service DNS inside Compose; local dev may override FRONTEND_URL. */
function defaultFrontendUrl() {
  const explicit = String(process.env.FRONTEND_URL || "").trim();
  if (explicit) return explicit.replace(/\/+$/, "");
  const inDocker = String(process.env.NEYRA_DOCKER || process.env.DOCKER_ENV || "").trim() === "1";
  if (inDocker) return "http://neyra-web:3000";
  return "http://localhost:3000";
}

function json(res, status, payload) {
  const body = JSON.stringify(payload ?? {}, null, 2);
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(body),
  });
  res.end(body);
}

function readBody(req) {
  return new Promise((resolve) => {
    let data = "";
    req.on("data", (c) => (data += c));
    req.on("end", () => {
      try {
        resolve(data ? JSON.parse(data) : {});
      } catch {
        resolve({});
      }
    });
  });
}

function listArtifacts(dir, extLower) {
  const out = [];
  try {
    if (!fs.existsSync(dir)) return out;
    const walk = (d) => {
      for (const ent of fs.readdirSync(d, { withFileTypes: true })) {
        const p = path.join(d, ent.name);
        if (ent.isDirectory()) walk(p);
        else if (ent.isFile() && ent.name.toLowerCase().endsWith(extLower)) out.push(p);
      }
    };
    walk(dir);
  } catch {
    return out;
  }
  return out.sort();
}

function listScreenshots(testResultsDir) {
  return listArtifacts(testResultsDir, ".png");
}

function listTraces(testResultsDir) {
  return listArtifacts(testResultsDir, ".zip").filter((p) => /trace/i.test(path.basename(p)));
}

/**
 * Wait until GET / returns 2xx (frontend boot).
 */
async function waitForFrontendReady(baseURL, opts = {}) {
  const maxMs = opts.maxMs ?? 120_000;
  const intervalMs = opts.intervalMs ?? 1500;
  const url = `${String(baseURL || "").replace(/\/+$/, "")}/`;
  const started = Date.now();
  let lastErr = "";
  while (Date.now() - started < maxMs) {
    try {
      const res = await fetch(url, { redirect: "follow", signal: AbortSignal.timeout(8000) });
      if (res.ok || (res.status >= 200 && res.status < 400)) return { ok: true };
      lastErr = `HTTP ${res.status}`;
    } catch (e) {
      lastErr = `${e?.name || "Error"}: ${String(e?.message || e)}`;
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  return { ok: false, error: lastErr || "timeout" };
}

function parsePlaywrightFailure(stdout, stderr, testResultsDir) {
  const blob = `${stdout || ""}\n${stderr || ""}`;
  let firstFailedTest = "";
  const mTest = blob.match(/›\s*(tests\/[^\s]+\.spec\.ts[^\n]*)/);
  if (mTest) firstFailedTest = mTest[1].trim();

  let firstErrorLine = "";
  const errLines = blob.split("\n").filter((ln) => /Error:|expect\(|\bTimeout\b/i.test(ln));
  if (errLines.length) firstErrorLine = errLines[0].slice(0, 500);

  let failedSelector = "";
  const mLoc = blob.match(/locator\(([^)]+)\)/);
  if (mLoc) failedSelector = mLoc[1].slice(0, 300);

  const shots = listScreenshots(testResultsDir);
  const traces = listTraces(testResultsDir);
  const firstScreenshot = shots[0] ? path.relative(process.cwd(), shots[0]).replace(/\\/g, "/") : "";
  const firstTrace = traces[0] ? path.relative(process.cwd(), traces[0]).replace(/\\/g, "/") : "";

  return {
    first_failed_test: firstFailedTest,
    first_error_line: firstErrorLine,
    failed_selector: failedSelector,
    first_screenshot: firstScreenshot,
    first_trace: firstTrace,
  };
}

async function runPlaywright({ baseURL, email, password }) {
  const startedAt = Date.now();
  const metricsPath = "/tmp/deep_qa_metrics.json";
  const testResultsDir = path.resolve("test-results");

  // Clean old artifacts best-effort.
  try {
    if (fs.existsSync(metricsPath)) fs.unlinkSync(metricsPath);
  } catch {}

  const env = {
    ...process.env,
    NEYRA_DOCKER: process.env.NEYRA_DOCKER || "1",
    PLAYWRIGHT_BASE_URL: baseURL,
    DEEP_QA_EMAIL: email,
    DEEP_QA_PASSWORD: password,
    DEEP_QA_METRICS_PATH: metricsPath,
    /** Always run full Deep QA flows in CI/Docker (was gated behind DEEP_QA_FULL). */
    DEEP_QA_FULL: "1",
  };

  // Do NOT parse Playwright JSON from stdout (warnings/logs can mix in).
  const args = ["playwright", "test", "tests/ui/deep-product.spec.ts", "--reporter=line"];
  const child = spawn("npx", args, { env, cwd: process.cwd() });

  let stdout = "";
  let stderr = "";
  child.stdout.on("data", (d) => (stdout += String(d)));
  child.stderr.on("data", (d) => (stderr += String(d)));

  const exitCode = await new Promise((resolve) => {
    child.on("close", (code) => resolve(typeof code === "number" ? code : 1));
  });

  const runtimeSeconds = Math.round(((Date.now() - startedAt) / 1000) * 100) / 100;

  let metrics = {};
  try {
    metrics = fs.existsSync(metricsPath) ? JSON.parse(fs.readFileSync(metricsPath, "utf-8") || "{}") : {};
  } catch {
    metrics = {};
  }
  const flowReport =
    metrics.flow_report && typeof metrics.flow_report === "object" && !Array.isArray(metrics.flow_report)
      ? metrics.flow_report
      : {};

  const parseFail = exitCode !== 0 ? parsePlaywrightFailure(stdout, stderr, testResultsDir) : {};

  const shots = listScreenshots(testResultsDir);
  const shotsRel = shots.map((p) => p.replace(process.cwd(), "").replace(/^[/\\]+/, "").replace(/\\/g, "/"));

  return {
    ok: exitCode === 0,
    exit_code: exitCode,
    runtime_seconds: runtimeSeconds,
    pages_visited: Number(metrics.pages_visited || 0),
    buttons_clicked: Number(metrics.buttons_clicked || 0),
    interactions_count: Number(metrics.interactions_count || 0),
    flows_completed: Array.isArray(metrics.flows_completed) ? metrics.flows_completed : [],
    flow_failures: metrics.flow_failures && typeof metrics.flow_failures === "object" ? metrics.flow_failures : {},
    flow_skip_reasons:
      metrics.flow_skip_reasons && typeof metrics.flow_skip_reasons === "object" ? metrics.flow_skip_reasons : {},
    flow_report: flowReport,
    auth_ok: metrics.auth_ok !== false,
    auth_error: typeof metrics.auth_error === "string" ? metrics.auth_error : "",
    screenshots: shotsRel.slice(0, 12),
    screenshots_count: shotsRel.length,
    stdout_tail: stdout.slice(-2000),
    stderr_tail: stderr.slice(-2000),
    ...parseFail,
  };
}

const server = http.createServer(async (req, res) => {
  if (req.method === "GET" && req.url === "/health") {
    return json(res, 200, { ok: true });
  }
  if (req.method === "POST" && req.url === "/run") {
    const body = await readBody(req);
    const baseURL = String(body.frontend_url || defaultFrontendUrl()).trim().replace(/\/+$/, "");
    const email = String(body.email || process.env.DEEP_QA_EMAIL || "qa_demo_a@neyra.local").trim();
    const password = String(body.password || process.env.DEEP_QA_PASSWORD || "qa-demo-only");
    const contractBase = {
      browser_used: true,
      auth_used: true,
      score: 0,
      runtime_seconds: 0,
      pages_visited: 0,
      buttons_clicked: 0,
      screenshots: [],
      issues: [],
      frontend_url_used: baseURL,
      frontend_reachable: false,
      auth_status: "unknown",
    };

    const ready = await waitForFrontendReady(baseURL);
    if (!ready.ok) {
      return json(res, 200, {
        ...contractBase,
        ok: false,
        score: 0,
        browser_used: false,
        issues: [
          {
            severity: "critical",
            title: "Frontend unreachable",
            details: `GET ${baseURL}/ failed after wait: ${ready.error || "unknown"}`,
            location: "deep-qa-runner:waitForFrontendReady",
            fix: "Ensure neyra-web is up (Docker) or run against http://localhost:3000 with the dev server running.",
          },
        ],
      });
    }

    try {
      const r = await runPlaywright({ baseURL, email, password });
      const ok = Boolean(r.ok);
      const pv = Number(r.pages_visited || 0);
      const bc = Number(r.buttons_clicked || 0);
      const authOk = r.auth_ok !== false && !r.auth_error;
      let score = 0;
      if (ok) {
        if (pv >= 5 && bc >= 8) score = 92;
        else if (pv >= 3 && bc >= 4) score = 88;
        else if (pv >= 1) score = 82;
        else score = 78;
      } else if (pv >= 1) {
        /* Partial run: surface non-zero score when browser progressed */
        score = 35;
      }

      const issues = [];
      if (r.auth_error) {
        issues.push({
          severity: "critical",
          title: "Deep QA auth failed",
          details: r.auth_error,
          location: "frontend/tests/ui/deep-product.spec.ts:loginAsDemo",
          fix: "Ensure QA demo user exists and DEEP_QA_EMAIL/PASSWORD match backend seed; check API_URL from qa-runner to api.",
        });
      }
      if (!ok) {
        const detailParts = [
          r.first_failed_test ? `Test: ${r.first_failed_test}` : "",
          r.failed_selector ? `Selector: ${r.failed_selector}` : "",
          r.first_screenshot ? `Screenshot: ${r.first_screenshot}` : "",
          r.first_trace ? `Trace: ${r.first_trace}` : "",
          r.first_error_line ? r.first_error_line : "",
          r.stderr_tail ? `stderr:\n${r.stderr_tail}` : "",
          r.stdout_tail ? `stdout:\n${r.stdout_tail}` : "",
        ].filter(Boolean);
        issues.push({
          severity: "critical",
          title: "Deep QA failed (Playwright)",
          details: detailParts.join("\n\n").slice(0, 3500),
          location: "frontend/tests/ui/deep-product.spec.ts",
          fix: "Open trace/screenshot under test-results, fix selector or app regression, rerun Deep QA.",
        });
      }

      const authStatus = r.auth_error ? "auth_failed" : r.auth_ok === true ? "ok" : ok ? "ok" : "unknown";

      return json(res, 200, {
        ...contractBase,
        ok,
        score,
        frontend_reachable: true,
        auth_status: authStatus,
        runtime_seconds: Number(r.runtime_seconds || 0),
        pages_visited: pv,
        buttons_clicked: bc,
        interactions_count: Number(r.interactions_count || 0),
        flows_completed: Array.isArray(r.flows_completed) ? r.flows_completed : [],
        flow_failures: r.flow_failures && typeof r.flow_failures === "object" ? r.flow_failures : {},
        flow_skip_reasons:
          r.flow_skip_reasons && typeof r.flow_skip_reasons === "object" ? r.flow_skip_reasons : {},
        flow_report: r.flow_report && typeof r.flow_report === "object" ? r.flow_report : {},
        screenshots: Array.isArray(r.screenshots) ? r.screenshots : [],
        screenshots_count: Number(r.screenshots_count || 0),
        exit_code: Number(r.exit_code ?? 1),
        first_failed_test: r.first_failed_test || "",
        failed_selector: r.failed_selector || "",
        first_screenshot: r.first_screenshot || "",
        first_trace: r.first_trace || "",
        issues,
        stdout_tail: String(r.stdout_tail || "").slice(0, 2000),
        stderr_tail: String(r.stderr_tail || "").slice(0, 2000),
      });
    } catch (e) {
      return json(res, 200, {
        ...contractBase,
        ok: false,
        score: 0,
        frontend_reachable: true,
        auth_status: "error",
        issues: [
          {
            severity: "critical",
            title: "Deep QA runner error",
            details: `${e?.name || "Error"}: ${String(e?.message || e)}`,
            location: "qa-runner",
            fix: "Check qa-runner logs, ensure Playwright + browsers are installed, then rerun.",
          },
        ],
      });
    }
  }
  return json(res, 404, { ok: false, error: "not_found" });
});

server.listen(PORT, "0.0.0.0", () => {
  // eslint-disable-next-line no-console
  console.error(`[deep-qa-runner] listening on :${PORT} default_frontend=${defaultFrontendUrl()}`);
});
