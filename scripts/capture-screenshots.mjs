import fs from "node:fs/promises";
import { existsSync, createReadStream } from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const MIME_TYPES = new Map([
  [".html", "text/html; charset=utf-8"],
  [".css", "text/css; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".png", "image/png"],
  [".jpg", "image/jpeg"],
  [".jpeg", "image/jpeg"],
  [".svg", "image/svg+xml; charset=utf-8"],
  [".webp", "image/webp"],
  [".ico", "image/x-icon"]
]);

function parseArgs(argv) {
  const args = {
    manifestPath: null,
    baseUrl: process.env.CAPTURE_BASE_URL || null,
    outputDir: null,
    headful: false,
    pruneFailed: false
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--base-url") {
      args.baseUrl = argv[++i];
    } else if (arg === "--out") {
      args.outputDir = argv[++i];
    } else if (arg === "--headful") {
      args.headful = true;
    } else if (arg === "--prune-failed") {
      args.pruneFailed = true;
    } else if (!args.manifestPath) {
      args.manifestPath = arg;
    } else {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }

  args.manifestPath ??= "test-site/screenshot-manifest.json";
  return args;
}

function safeJoin(root, requestPath) {
  const decodedPath = decodeURIComponent(requestPath.split("?")[0]);
  const normalized = path.normalize(decodedPath).replace(/^(\.\.[/\\])+/, "");
  const relativePath = normalized === "/" ? "index.html" : normalized.replace(/^[/\\]/, "");
  const resolved = path.resolve(root, relativePath);
  const rootWithSep = root.endsWith(path.sep) ? root : `${root}${path.sep}`;

  if (resolved !== root && !resolved.startsWith(rootWithSep)) {
    return null;
  }

  return resolved;
}

async function startStaticServer(root) {
  const server = http.createServer(async (request, response) => {
    const filePath = safeJoin(root, request.url || "/");

    if (!filePath || !existsSync(filePath)) {
      response.writeHead(404, { "content-type": "text/plain; charset=utf-8" });
      response.end("Not found");
      return;
    }

    const stats = await fs.stat(filePath);
    if (stats.isDirectory()) {
      response.writeHead(301, { location: `${request.url?.replace(/\/?$/, "/")}index.html` });
      response.end();
      return;
    }

    const contentType = MIME_TYPES.get(path.extname(filePath).toLowerCase()) || "application/octet-stream";
    response.writeHead(200, { "content-type": contentType });
    createReadStream(filePath).pipe(response);
  });

  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });

  const address = server.address();
  if (!address || typeof address === "string") {
    throw new Error("Could not read static server address");
  }

  return {
    baseUrl: `http://127.0.0.1:${address.port}`,
    close: () => new Promise((resolve, reject) => server.close((error) => (error ? reject(error) : resolve())))
  };
}

function resolvePathFromManifest(manifestDir, value) {
  return path.resolve(manifestDir, value);
}

async function stampManifestElements(page) {
  await page.evaluate(() => {
    const stampAttr = "data-wde-manifest-id";
    const cleanText = (value) => (value || "").replace(/\s+/g, " ").trim();
    const cssEscape = (value) => window.CSS && CSS.escape
      ? CSS.escape(value)
      : String(value).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
    const slug = (value) => cleanText(value)
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 48) || "element";
    const accessibleName = (el) => {
      const aria = el.getAttribute("aria-label");
      if (aria) return cleanText(aria);
      const labelledBy = el.getAttribute("aria-labelledby");
      if (labelledBy) {
        const text = labelledBy.split(/\s+/).map((id) => document.getElementById(id)?.innerText || "").join(" ");
        if (cleanText(text)) return cleanText(text);
      }
      if (el.id) {
        const label = document.querySelector(`label[for="${cssEscape(el.id)}"]`);
        if (label && cleanText(label.innerText)) return cleanText(label.innerText);
      }
      const closestLabel = el.closest("label");
      if (closestLabel && cleanText(closestLabel.innerText)) return cleanText(closestLabel.innerText);
      const alt = el.getAttribute("alt");
      if (alt) return cleanText(alt);
      const title = el.getAttribute("title");
      if (title) return cleanText(title);
      const value = el.getAttribute("value");
      if (value && ["input", "button"].includes(el.tagName.toLowerCase())) return cleanText(value);
      return cleanText(el.innerText || el.textContent || "");
    };

    Array.from(document.querySelectorAll("*")).forEach((el, index) => {
      if (el.hasAttribute(stampAttr)) return;
      const tag = el.tagName.toLowerCase();
      const label = accessibleName(el) || el.id || el.getAttribute("name") || tag;
      el.setAttribute(stampAttr, `wde-${index}-${tag}-${slug(label)}`);
    });
  });
}

async function removeEvaluatorAttributes(page) {
  await page.evaluate(() => {
    for (const el of Array.from(document.querySelectorAll("[data-wde-manifest-id]"))) {
      el.removeAttribute("data-wde-manifest-id");
    }
  });
}

function actionTimeout(defaults, action) {
  return action.timeoutMs ?? defaults.actionTimeoutMs ?? 5000;
}

async function runAction(page, action, defaults) {
  const settleMs = action.settleMs ?? 0;
  const options = { timeout: actionTimeout(defaults, action) };

  if (action.type === "hover") {
    await page.locator(action.selector).hover(options);
  } else if (action.type === "click") {
    await page.locator(action.selector).click(options);
  } else if (action.type === "focus") {
    await page.locator(action.selector).focus(options);
  } else if (action.type === "fill") {
    await page.locator(action.selector).fill(action.value ?? "", options);
  } else if (action.type === "press") {
    await page.keyboard.press(action.key);
  } else if (action.type === "wait") {
    await page.waitForTimeout(action.ms);
  } else if (action.type === "waitForSelector") {
    await page.locator(action.selector).waitFor({
      state: action.state ?? "visible",
      timeout: action.timeoutMs
    });
  } else if (action.type === "scroll") {
    if (action.selector) {
      await page.locator(action.selector).scrollIntoViewIfNeeded();
    } else {
      await page.evaluate(({ x = 0, y = 0 }) => window.scrollTo(x, y), action);
    }
  } else if (action.type === "scrollBy") {
    await page.evaluate(({ x = 0, y = 0 }) => window.scrollBy(x, y), action);
  } else {
    throw new Error(`Unknown action type: ${action.type}`);
  }

  if (settleMs > 0) {
    await page.waitForTimeout(settleMs);
  }
}

function screenshotOptions(defaults, capture, outputPath) {
  return {
    path: outputPath,
    fullPage: Boolean(capture.screenshot?.fullPage ?? defaults.screenshot?.fullPage),
    animations: capture.screenshot?.animations ?? defaults.screenshot?.animations ?? "disabled",
    caret: capture.screenshot?.caret ?? defaults.screenshot?.caret ?? "hide",
    clip: capture.screenshot?.clip
  };
}

function compactError(error) {
  return String(error?.message || error || "unknown error")
    .replace(/\u001b\[[0-9;]*m/g, "")
    .split("\n")
    .slice(0, 12)
    .join("\n");
}

function isRequiredCapture(capture) {
  return (capture.actions ?? []).length === 0;
}

async function runCapture({ browser, baseUrl, defaults, capture, outputDir }) {
  const page = await browser.newPage({
    deviceScaleFactor: defaults.deviceScaleFactor ?? 1
  });

  try {
    const viewport = capture.viewport ?? defaults.viewport;
    if (!viewport) {
      throw new Error(`Capture ${capture.id} is missing a viewport`);
    }

    await page.setViewportSize(viewport);

    if (capture.colorScheme || defaults.colorScheme) {
      await page.emulateMedia({ colorScheme: capture.colorScheme ?? defaults.colorScheme });
    }

    const capturePath = capture.path ?? capture.urlPath;
    if (!capturePath) {
      throw new Error(`Capture ${capture.id} is missing a path`);
    }

    const url = new URL(capturePath, baseUrl).toString();
    await page.goto(url, {
      waitUntil: capture.waitUntil ?? defaults.waitUntil ?? "networkidle",
      timeout: capture.timeoutMs ?? defaults.timeoutMs ?? 30000
    });

    if (defaults.afterLoadWaitMs) {
      await page.waitForTimeout(defaults.afterLoadWaitMs);
    }

    await stampManifestElements(page);

    for (const action of capture.actions ?? []) {
      await runAction(page, action, defaults);
    }

    const fileName = capture.file ?? `${capture.id}.png`;
    const outputPath = path.join(outputDir, fileName);
    await fs.mkdir(path.dirname(outputPath), { recursive: true });
    await removeEvaluatorAttributes(page);
    await page.screenshot(screenshotOptions(defaults, capture, outputPath));
    console.log(`${capture.id} -> ${path.relative(process.cwd(), outputPath)}`);
    return { id: capture.id, status: "ok", required: isRequiredCapture(capture), file: fileName };
  } finally {
    await page.close().catch(() => {});
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const manifestPath = path.resolve(args.manifestPath);
  const manifestDir = path.dirname(manifestPath);
  const manifest = JSON.parse(await fs.readFile(manifestPath, "utf8"));
  const defaults = manifest.defaults ?? {};

  const outputDir = path.resolve(
    args.outputDir
      ? args.outputDir
      : resolvePathFromManifest(manifestDir, manifest.outputDir ?? "screenshots")
  );
  if (manifest.cleanOutputDir) {
    await fs.rm(outputDir, { recursive: true, force: true });
  }
  await fs.mkdir(outputDir, { recursive: true });

  let staticServer = null;
  let baseUrl = args.baseUrl || manifest.site?.baseUrl || manifest.baseUrl || null;

  if (!baseUrl) {
    const siteRoot = resolvePathFromManifest(manifestDir, manifest.site?.root ?? ".");
    staticServer = await startStaticServer(siteRoot);
    baseUrl = staticServer.baseUrl;
    console.log(`Serving ${siteRoot} at ${baseUrl}`);
  }

  const launchOptions = { headless: !args.headful };
  if (process.env.PLAYWRIGHT_CHANNEL) {
    launchOptions.channel = process.env.PLAYWRIGHT_CHANNEL;
  }

  const browser = await chromium.launch(launchOptions);
  const results = [];

  try {
    for (const capture of manifest.captures) {
      if (capture.enabled === false) {
        console.log(`${capture.id} skipped`);
        results.push({ id: capture.id, status: "skipped", required: false });
        continue;
      }

      try {
        results.push(await runCapture({ browser, baseUrl, defaults, capture, outputDir }));
      } catch (error) {
        const required = isRequiredCapture(capture);
        const failure = {
          id: capture.id,
          status: "failed",
          required,
          error: compactError(error)
        };
        results.push(failure);
        console.error(`[capture failed] ${capture.id}${required ? " required" : " optional"}: ${failure.error}`);
      }
    }
  } finally {
    await browser.close();
    if (staticServer) {
      await staticServer.close();
    }
  }

  const failed = results.filter((result) => result.status === "failed");
  const requiredFailures = failed.filter((result) => result.required);
  const optionalFailures = failed.filter((result) => !result.required);
  const droppedIds = new Set(optionalFailures.map((result) => result.id));

  if (args.pruneFailed && droppedIds.size > 0) {
    manifest.captures = manifest.captures.filter((capture) => !droppedIds.has(capture.id));
    await fs.writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
    console.log(`Dropped ${droppedIds.size} failed optional capture(s) from ${path.relative(process.cwd(), manifestPath)}`);
  }

  const reportPath = path.join(outputDir, "_replay-report.json");
  await fs.writeFile(
    reportPath,
    `${JSON.stringify({
      manifestPath,
      pruneFailed: args.pruneFailed,
      ok: results.filter((result) => result.status === "ok").length,
      failed: failed.length,
      droppedCaptures: Array.from(droppedIds),
      results
    }, null, 2)}\n`,
    "utf8"
  );

  if (requiredFailures.length > 0) {
    throw new Error(`${requiredFailures.length} required capture(s) failed; see ${reportPath}`);
  }
  if (!args.pruneFailed && failed.length > 0) {
    throw new Error(`${failed.length} capture(s) failed; see ${reportPath}`);
  }
  if (results.filter((result) => result.status === "ok").length === 0) {
    throw new Error(`No captures succeeded; see ${reportPath}`);
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
