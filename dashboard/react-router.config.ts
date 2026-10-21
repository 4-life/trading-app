import type { Config } from "@react-router/dev/config";

export default {
  ssr: true,
  // Behind the HTTPS proxy the dashboard sees itself as http:// while the
  // browser's Origin is https://<domain> - React Router's CSRF check on actions
  // would refuse every form post. The public domain (DOMAIN, baked in at build
  // by CI) is allowed instead; locally (http://localhost) nothing is needed.
  allowedActionOrigins: process.env.DOMAIN ? [process.env.DOMAIN] : [],
} satisfies Config;
