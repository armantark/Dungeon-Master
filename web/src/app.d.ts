// Vite picks up CSS via side-effect imports; this declaration tells the
// TypeScript compiler that those imports are valid module references.

declare module "*.css";
declare module "*.css?inline" {
  const content: string;
  export default content;
}
