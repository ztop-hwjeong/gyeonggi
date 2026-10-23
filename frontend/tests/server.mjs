import { cpSync } from "node:fs";

cpSync(".next/static", ".next/standalone/.next/static", { recursive: true });
await import("../.next/standalone/server.js");
