/** @type {import('next').NextConfig} */
const nextConfig = {
  experimental: {
    // Allow long-running AI calls (market analysis, brand generation) up to 3 min
    proxyTimeout: 180_000,
  },
  async rewrites() {
    const api = process.env.INTERNAL_API_URL || 'http://127.0.0.1:8000'
    return [
      {
        source: '/api/v1/:path*',
        destination: `${api}/api/v1/:path*`,
      },
      {
        source: '/health',
        destination: `${api}/health`,
      },
      {
        source: '/storage/stats',
        destination: `${api}/storage/stats`,
      },
    ]
  },
}

export default nextConfig
