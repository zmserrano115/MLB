import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  transpilePackages: ["@all-rise/shared-types", "@all-rise/ui"],
};

export default nextConfig;
