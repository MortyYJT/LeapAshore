import assert from "node:assert/strict";
import { test } from "node:test";

import { NAV_HREFS, clickDestination, clickQuery, isNavCurrent, pushDestination, pushQuery, routeShape, type LinkClick } from "./navigation.ts";

const HERE = { origin: "https://app.example", pathname: "/" };
const click = (href: string, over: Partial<LinkClick> = {}): LinkClick => ({
  href: new URL(href, HERE.origin).href,
  button: 0,
  metaKey: false,
  ctrlKey: false,
  shiftKey: false,
  altKey: false,
  defaultPrevented: true,
  ...over,
});
const current = (pathname: string) => NAV_HREFS.filter((href) => isNavCurrent(href, pathname));

test("each top-level route marks exactly its own rail entry", () => {
  for (const href of NAV_HREFS) assert.deepEqual(current(href), [href]);
});

test("the overview is current only on /", () => {
  assert.equal(isNavCurrent("/", "/roadmap"), false);
  assert.equal(isNavCurrent("/", "/"), true);
});

test("pages reached from a section keep that section current", () => {
  assert.deepEqual(current("/portfolio"), ["/applications"]);
  assert.deepEqual(current("/tiers"), ["/applications"]);
  assert.deepEqual(current("/schools/ucl"), ["/schools"]);
  assert.deepEqual(current("/programs/cricos-0100139"), ["/schools"]);
});

test("a path that only shares a prefix is not that section", () => {
  assert.deepEqual(current("/schoolsmith"), []);
  assert.deepEqual(current("/me"), []);
  assert.deepEqual(current("/privacy"), []);
});

test("the destination of a click marks only its own rail entry", () => {
  // The shell draws the rail from the click's destination while the navigation is pending.
  const pending = clickDestination(click("/schools"), HERE);
  assert.equal(pending, "/schools");
  assert.deepEqual(current(pending ?? HERE.pathname), ["/schools"]);
});

test("every route has a shape", () => {
  const shapes: [string, string][] = [
    ["/", "overview"],
    ["/roadmap", "roadmap"],
    ["/applications", "applications"],
    ["/materials", "materials"],
    ["/schools", "schools"],
    ["/schools/ucl", "school"],
    ["/programs/cricos-0100139", "program"],
    ["/tiers", "tiers"],
    ["/assess", "tiers"],
    ["/portfolio", "portfolio"],
    ["/advisor", "advisor"],
    ["/me", "me"],
    ["/privacy", "privacy"],
    ["/reminders/unsubscribe", "unsubscribe"],
    ["/admin", "admin"],
    ["/admin/sources/12", "admin"],
    ["/schools/", "schools"],
  ];
  for (const [path, shape] of shapes) assert.equal(routeShape(path), shape, path);
});

test("paths that are not app routes have no shape", () => {
  for (const path of ["/api/documents/3/download", "/logos/ucl.png", "/sw.js", "/programs", "/schools/a/b", "/nowhere", "/admin/sources"]) {
    assert.equal(routeShape(path), null, path);
  }
});

test("a plain click on an in-app link switches at once", () => {
  assert.equal(clickDestination(click("/roadmap"), HERE), "/roadmap");
  assert.equal(clickDestination(click("/applications?add=1"), HERE), "/applications");
  assert.equal(clickDestination(click("/schools/ucl#programs"), HERE), "/schools/ucl");
  assert.equal(clickDestination(click("/", {}), { ...HERE, pathname: "/schools" }), "/");
});

test("clicks that open elsewhere or are not navigations do not switch", () => {
  assert.equal(clickDestination(click("/roadmap", { metaKey: true }), HERE), null);
  assert.equal(clickDestination(click("/roadmap", { ctrlKey: true }), HERE), null);
  assert.equal(clickDestination(click("/roadmap", { shiftKey: true }), HERE), null);
  assert.equal(clickDestination(click("/roadmap", { altKey: true }), HERE), null);
  assert.equal(clickDestination(click("/roadmap", { button: 1 }), HERE), null);
  assert.equal(clickDestination(click("/roadmap", { target: "_blank" }), HERE), null);
  assert.equal(clickDestination(click("/roadmap", { download: true }), HERE), null);
  // A plain anchor the router did not take over is a full page load; the browser shows that itself.
  assert.equal(clickDestination(click("/roadmap", { defaultPrevented: false }), HERE), null);
  // The link's own handler may keep the visitor on the page (让顾问去查 opens the dock).
  assert.equal(clickDestination(click("/advisor?q=x", { local: true }), HERE), null);
});

test("another origin, a non-route and the page already on screen do not switch", () => {
  assert.equal(clickDestination(click("https://other.example/roadmap"), HERE), null);
  assert.equal(clickDestination(click("/api/documents/3/download"), HERE), null);
  assert.equal(clickDestination(click("/?demo=1"), HERE), null);
  assert.equal(clickDestination(click("/schools?page=2"), { ...HERE, pathname: "/schools" }), null);
  assert.equal(clickDestination(click("#main"), HERE), null);
});

test("a programmatic push follows the same rule", () => {
  assert.equal(pushDestination("/advisor", HERE), "/advisor");
  assert.equal(pushDestination("/schools?q=ucl", HERE), "/schools");
  assert.equal(pushDestination("/", HERE), null);
  assert.equal(pushDestination("https://other.example/", HERE), null);
  assert.equal(pushDestination("/api/health", HERE), null);
});

const ON_SCHOOLS = { origin: HERE.origin, pathname: "/schools", search: "?q=ucl" };

test("a click that only changes the query of the page on screen is a refresh of that page", () => {
  assert.equal(clickQuery(click("/schools?q=ucl&page=2"), ON_SCHOOLS), "?q=ucl&page=2");
  assert.equal(clickQuery(click("/schools"), ON_SCHOOLS), "");
  assert.equal(pushQuery("/schools?q=melbourne", ON_SCHOOLS), "?q=melbourne");
  assert.equal(pushQuery("/schools?q=ucl", { ...ON_SCHOOLS, search: "q=ucl" }), null);
});

test("a query refresh is not reported for another page, the same query, or a click the router did not take", () => {
  assert.equal(clickQuery(click("/schools?q=ucl"), ON_SCHOOLS), null);
  assert.equal(clickQuery(click("/roadmap?x=1"), ON_SCHOOLS), null);
  assert.equal(clickQuery(click("/schools?page=2", { metaKey: true }), ON_SCHOOLS), null);
  assert.equal(clickQuery(click("/schools?page=2", { defaultPrevented: false }), ON_SCHOOLS), null);
  assert.equal(pushQuery("https://elsewhere.example/schools?page=2", ON_SCHOOLS), null);
});
