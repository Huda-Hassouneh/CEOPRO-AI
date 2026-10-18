import assert from "node:assert/strict";
import test from "node:test";
import app from "../../src/app.js";
import authRouter from "../../src/modules/auth/index.js";
import onboardingRouter from "../../src/modules/onboarding/index.js";

function mountedRouters() {
  return (app as any).router.stack
    .filter((layer: any) => layer.name === "router")
    .map((layer: any) => layer.handle);
}

function routes(router: any) {
  return router.stack
    .filter((layer: any) => layer.route)
    .map((layer: any) => ({
      path: layer.route.path,
      methods: Object.keys(layer.route.methods)
    }));
}

test("the app mounts auth and onboarding routers and registers their endpoints", () => {
  const mounted = mountedRouters();
  assert.ok(mounted.includes(authRouter));
  assert.ok(mounted.includes(onboardingRouter));

  const auth = routes(authRouter);
  for (const [path, method] of [
    ["/login", "post"],
    ["/register", "post"],
    ["/me", "get"],
    ["/change-password", "post"],
    ["/session", "get"],
    ["/logout", "post"]
  ]) {
    assert.ok(auth.some((route: any) => route.path === path && route.methods.includes(method)));
  }

  const onboarding = routes(onboardingRouter);
  for (const [path, method] of [
    ["/state", "get"],
    ["/regional-preferences", "patch"],
    ["/profile", "patch"],
    ["/goals", "patch"],
    ["/plan", "patch"],
    ["/complete", "post"]
  ]) {
    assert.ok(onboarding.some((route: any) => route.path === path && route.methods.includes(method)));
  }
});
