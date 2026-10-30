import { readFileSync, writeFileSync } from "node:fs";

const source = new URL("./design-tokens.json", import.meta.url);
const { tokens } = JSON.parse(readFileSync(source, "utf8"));
const declarations = Object.entries(tokens).map(([name, token]) => {
  const value = token.value.replace(/\{([^}]+)\}/g, (_, reference) => {
    if (!(reference in tokens)) throw new Error(`Unknown token: ${reference}`);
    return `var(--${reference.replaceAll(".", "-")})`;
  });
  return `  --${name.replaceAll(".", "-")}: ${value};`;
});
writeFileSync(
  new URL("./tokens.css", import.meta.url),
  `/* design-tokens.json에서 생성한 공통 토큰 */\n:root {\n${declarations.join("\n")}\n}\n`,
);
