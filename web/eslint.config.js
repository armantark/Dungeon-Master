import js from "@eslint/js";
import prettier from "eslint-config-prettier";
import svelte from "eslint-plugin-svelte";
import globals from "globals";
import ts from "typescript-eslint";

export default ts.config(
  {
    ignores: ["dist/**", "node_modules/**", "src-tauri/target/**"],
  },
  js.configs.recommended,
  ...ts.configs.recommendedTypeChecked,
  ...ts.configs.stylisticTypeChecked,
  ...svelte.configs.recommended,
  {
    languageOptions: {
      globals: {
        ...globals.browser,
        ...globals.node,
      },
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
  },
  {
    files: ["**/*.svelte", "**/*.svelte.ts", "**/*.svelte.js"],
    languageOptions: {
      parserOptions: {
        projectService: true,
        extraFileExtensions: [".svelte"],
        parser: ts.parser,
        tsconfigRootDir: import.meta.dirname,
      },
    },
  },
  {
    ...ts.configs.disableTypeChecked,
    files: ["*.config.js"],
    languageOptions: {
      ...ts.configs.disableTypeChecked.languageOptions,
      globals: globals.node,
      parserOptions: {
        projectService: false,
      },
    },
  },
  {
    files: ["src/components/architecture/ArchitectureExplainer.svelte"],
    rules: {
      "svelte/no-navigation-without-resolve": "off",
    },
  },
  prettier,
);
