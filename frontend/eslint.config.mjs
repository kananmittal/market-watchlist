import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  globalIgnores([".next/**", "out/**", "build/**", "next-env.d.ts"]),
  {
    // These pages fetch on mount and set loading/data/error state in the
    // async callback's finally block. React 19's set-state-in-effect rule
    // flags the whole pattern, but the calls are not synchronous effect-body
    // updates and do not cause cascading renders. The alternative the rule
    // suggests (a data-fetching library) is more dependency than this
    // hackathon-scoped app warrants.
    files: ["src/app/**/page.tsx"],
    rules: { "react-hooks/set-state-in-effect": "off" },
  },
]);

export default eslintConfig;
