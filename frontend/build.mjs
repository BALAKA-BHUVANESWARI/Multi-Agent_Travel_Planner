// Builds the web app into dist/, which the backend serves.
//   npm run build   once, minified
//   npm run watch   rebuild on every change while editing (reload the browser to see it)
import { copyFileSync, mkdirSync, rmSync } from "node:fs";
import * as esbuild from "esbuild";

const watch = process.argv.includes("--watch");
const options = {
  entryPoints: { app: "app/main.jsx" },
  outdir: "dist",
  bundle: true,
  jsx: "automatic",
  target: ["es2020"],
  minify: !watch,
  sourcemap: true,
  define: { "process.env.NODE_ENV": JSON.stringify(watch ? "development" : "production") },
  logLevel: "info",
};

rmSync("dist", { recursive: true, force: true });
mkdirSync("dist");
copyFileSync("index.html", "dist/index.html");
// the vector map libraries are ready-made browser files, loaded by index.html next to app.js
for (const file of ["maplibre-gl/dist/maplibre-gl.js", "maplibre-gl/dist/maplibre-gl.css",
  "@maplibre/maplibre-gl-leaflet/leaflet-maplibre-gl.js"]) {
  copyFileSync(`node_modules/${file}`, `dist/${file.split("/").pop()}`);
}

if (watch) {
  const context = await esbuild.context(options);
  await context.watch();
} else {
  await esbuild.build(options);
}
