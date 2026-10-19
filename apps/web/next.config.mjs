/** @type {import('next').NextConfig} */
// The console is a pure client-side SPA over the control-plane REST/SSE API, so it is
// exported statically (output: "export") and shipped inside the Electron asar bundle.
// Nothing here needs a Node server at runtime.
const nextConfig = {
  reactStrictMode: true,
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  env: {
    NEXT_PUBLIC_REVIVE_API_URL: process.env.NEXT_PUBLIC_REVIVE_API_URL ?? "/",
  },
};

export default nextConfig;
