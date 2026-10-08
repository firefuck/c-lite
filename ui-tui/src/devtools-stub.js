// A stub for `react-devtools-core`, which ink imports eagerly but we never use.
// esbuild aliases the import here, so the bundled .mjs does not try to resolve a package the
// user does not have. The devtools hook is a no-op: `connectToDevTools` does nothing.
export default { connectToDevTools() {} };
