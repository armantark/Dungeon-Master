/// <reference types="vite/client" />

// Vite picks up CSS via side-effect imports; this declaration tells the
// TypeScript compiler that those imports are valid module references.

declare module "*.css";
declare module "*.css?inline" {
  const content: string;
  export default content;
}

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_ENABLE_ARCHITECTURE_MAP?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
