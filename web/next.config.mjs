/** @type {import('next').NextConfig} */
const nextConfig = {
  // Standalone output so the Docker image ships a minimal self-contained server.
  output: "standalone",
};

export default nextConfig;
