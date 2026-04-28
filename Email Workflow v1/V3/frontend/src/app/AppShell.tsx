import { useLayoutEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

// Same animation pattern as the AI-mode selector in SettingsPage:
// position the indicator absolutely behind the nav links, measure the
// active link's offset/height on every route change (and on resize),
// and let CSS transition handle the slide. Vertical instead of
// horizontal because the sidebar is a column.
const NAV_ITEMS: ReadonlyArray<{ to: string; label: string }> = [
  { to: "/inbox", label: "Inbox" },
  { to: "/review", label: "Review" },
  { to: "/settings", label: "Settings" },
];

export function AppShell() {
  const location = useLocation();
  const navLinkRefs = useRef<Array<HTMLAnchorElement | null>>([]);
  // Track the very first measurement so we can disable the CSS
  // transition on initial mount — otherwise the indicator visibly
  // slides from (0,0) to its target position on every page load.
  const firstMeasurementDoneRef = useRef(false);
  const [indicator, setIndicator] = useState<{
    top: number;
    left: number;
    width: number;
    height: number;
    ready: boolean;
    animate: boolean;
  }>({
    top: 0,
    left: 0,
    width: 0,
    height: 0,
    ready: false,
    animate: false,
  });

  // Find which nav item matches the current URL. NavLink's "active"
  // semantics use startsWith for nested routes (e.g. /threads/:id is
  // not in NAV_ITEMS, so the indicator hides until the user navigates
  // to one of the top-level routes again).
  const activeIndex = NAV_ITEMS.findIndex(
    (item) =>
      location.pathname === item.to ||
      location.pathname.startsWith(`${item.to}/`),
  );

  // useLayoutEffect (vs useEffect) so the measurement runs before
  // browser paint, avoiding a one-frame flash at the wrong position.
  useLayoutEffect(() => {
    function measure() {
      if (activeIndex < 0) {
        setIndicator((current) => ({ ...current, ready: false }));
        return;
      }
      const target = navLinkRefs.current[activeIndex];
      if (!target) return;
      const isFirst = !firstMeasurementDoneRef.current;
      setIndicator({
        top: target.offsetTop,
        left: target.offsetLeft,
        width: target.offsetWidth,
        height: target.offsetHeight,
        ready: true,
        animate: !isFirst,
      });
      if (isFirst) {
        firstMeasurementDoneRef.current = true;
        // Enable transitions AFTER the no-transition initial position
        // commits to the DOM, so future route changes glide.
        requestAnimationFrame(() => {
          setIndicator((current) => ({ ...current, animate: true }));
        });
      }
    }
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [activeIndex, location.pathname]);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div>
          <p className="eyebrow">Inter-Op</p>
          <h2>Inter-Email</h2>
          <p className="sidebar-copy">
            Product-grade queue, review, and draft workflow.
          </p>
        </div>

        <nav className="nav" style={{ position: "relative" }}>
          {/*
            Animated active-state indicator. Slides between nav items on
            route change. Sits behind the links (zIndex 0); links render
            on top with transparent background (zIndex 1) — we override
            the existing .nav a.active CSS rule (which sets its own
            background + border) to make this slider the SINGLE visual
            indicator instead of having two competing highlights.
          */}
          <span
            aria-hidden="true"
            style={{
              position: "absolute",
              left: indicator.left,
              top: indicator.top,
              width: indicator.width,
              height: indicator.height,
              background: "var(--surface-strong, rgba(255, 255, 255, 0.10))",
              border: "1px solid var(--border, rgba(255, 255, 255, 0.18))",
              borderRadius: "16px",
              boxShadow: "var(--shadow, 0 4px 14px rgba(0, 0, 0, 0.12))",
              // First measurement is no-transition so we land instantly;
              // subsequent moves use a smooth Material-style ease.
              transition: indicator.animate
                ? "left 280ms cubic-bezier(0.4, 0, 0.2, 1), top 280ms cubic-bezier(0.4, 0, 0.2, 1), width 280ms cubic-bezier(0.4, 0, 0.2, 1), height 280ms cubic-bezier(0.4, 0, 0.2, 1)"
                : "none",
              opacity: indicator.ready ? 1 : 0,
              pointerEvents: "none",
              zIndex: 0,
            }}
          />

          {NAV_ITEMS.map((item, index) => (
            <NavLink
              key={item.to}
              to={item.to}
              ref={(element) => {
                navLinkRefs.current[index] = element;
              }}
              // NavLink supports a function-style `style` prop that
              // receives `{ isActive }` from React Router — we use it
              // to (a) override the existing .nav a.active background
              // / border / shadow so our slider is the only visual
              // indicator, and (b) bold the label of the active route.
              style={({ isActive }) => ({
                position: "relative",
                zIndex: 1,
                background: "transparent",
                borderColor: "transparent",
                boxShadow: "none",
                fontWeight: isActive ? 700 : 500,
                transition: "font-weight 200ms ease",
              })}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>

      <main className="main-content">
        <Outlet />
      </main>
    </div>
  );
}
