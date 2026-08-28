import fs from "node:fs/promises";
import path from "node:path";

const root = process.cwd();
const source = path.join(root, "web");
const dist = path.join(root, "dist");
await fs.rm(dist, { recursive: true, force: true });
await fs.cp(source, dist, { recursive: true });

const required = [
  "index.html", "methodology/index.html", "assets/styles.css", "assets/app.js", "assets/format.js", "data/latest.json"
];
for (const file of required) {
  await fs.access(path.join(dist, file));
}
const indexPath = path.join(dist, "index.html");
let html = await fs.readFile(indexPath, "utf8");
const formatModule = await fs.readFile(path.join(dist, "assets/format.js"), "utf8");
const bundledData = JSON.parse(await fs.readFile(path.join(dist, "data/latest.json"), "utf8"));
const publicDataBase = process.env.R2_PUBLIC_BASE_URL?.trim().replace(/\/+$/, "");
if (publicDataBase) {
  const url = new URL(`${publicDataBase}/summary/latest.json`);
  const localHttp = url.protocol === "http:" && ["localhost", "127.0.0.1"].includes(url.hostname);
  if (url.protocol !== "https:" && !localHttp) {
    throw new Error("R2_PUBLIC_BASE_URL must use HTTPS (except localhost previews). ");
  }
  html = html.replace(/<body data-source="[^"]*">/, `<body data-source="${url.href}">`);
  await fs.writeFile(indexPath, html, "utf8");
}
if (bundledData.meta.status === "demo" && !formatModule.includes("DEMO DATA")) {
  throw new Error("Demo data must be visibly identified by the application status UI.");
}
if (/<(?:script|link)\b[^>]*(?:src|href)=["']https?:\/\/[^"']+["']/i.test(html)) {
  throw new Error("Remote executable assets are not allowed.");
}
console.log(`STREAM PULSE build complete: ${dist}`);
