import { type RouteConfig, index, route } from "@react-router/dev/routes";

export default [
  index("routes/home.tsx"),
  route("login", "routes/login.tsx"),
  route("logout", "routes/logout.tsx"),
  route("password", "routes/password.ts"),
  route("chart-candles", "routes/chart-candles.ts"),
  route("sweep-status", "routes/sweep-status.ts"),
  route("sweep-batch", "routes/sweep-batch.ts"),
] satisfies RouteConfig;
