import http from "node:http";
import fs from "node:fs";
import path from "node:path";

const root = path.join(process.cwd(), "dist");
const port = Number(process.env.PORT || 4173);
const mime = { ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".json": "application/json; charset=utf-8", ".svg": "image/svg+xml" };

http.createServer((request, response) => {
  const url = new URL(request.url || "/", `http://${request.headers.host || "localhost"}`);
  let pathname = decodeURIComponent(url.pathname).replace(/^\/+/, "");
  if (!pathname || pathname.endsWith("/")) pathname += "index.html";
  const target = path.resolve(root, pathname);
  if (!target.startsWith(path.resolve(root))) { response.writeHead(403).end("Forbidden"); return; }
  fs.stat(target, (error, stat) => {
    if (error || !stat.isFile()) { response.writeHead(404).end("Not found"); return; }
    response.writeHead(200, { "Content-Type": mime[path.extname(target)] || "application/octet-stream", "Cache-Control": "no-store" });
    fs.createReadStream(target).pipe(response);
  });
}).listen(port, "127.0.0.1", () => console.log(`STREAM PULSE preview: http://127.0.0.1:${port}/`));

