import type { NextConfig } from 'next';

const config: NextConfig = {
  output: 'standalone',
  poweredByHeader: false,
  allowedDevOrigins: ['127.0.0.1'],
  async rewrites() {
    return process.env.NODE_ENV === 'development'
      ? [{ source: '/api/:path*', destination: 'http://127.0.0.1:8000/:path*' }]
      : [];
  },
};

export default config;
