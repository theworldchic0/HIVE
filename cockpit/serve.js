// Tiny static server for the Trade Cockpit (localhost only).
const http = require("http");
const fs = require("fs");
const path = require("path");
const ROOT = __dirname;
const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json" };
http.createServer((req, res) => {
  const url = req.url.split("?")[0];
  const file = path.join(ROOT, url === "/" ? "index.html" : url);
  if (!file.startsWith(ROOT)) { res.writeHead(403); return res.end(); }
  fs.readFile(file, (err, data) => {
    if (err) { res.writeHead(404); return res.end("not found"); }
    res.writeHead(200, { "Content-Type": MIME[path.extname(file)] || "application/octet-stream" });
    res.end(data);
  });
}).listen(8788, "127.0.0.1", () => console.log("cockpit on http://127.0.0.1:8788"));
