import { useLayoutEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useQueueDashboard } from "../hooks/useApi";
import { useAcknowledgeAllMutation } from "../hooks/useApi";

// Same animation pattern as the AI-mode selector in SettingsPage:
// position the indicator absolutely behind the nav links, measure the
// active link's offset/height on every route change (and on resize),
// and let CSS transition handle the slide. Vertical instead of
// horizontal because the sidebar is a column.
const NAV_ITEMS: ReadonlyArray<{ to: string; label: string }> = [
  { to: "/dashboard", label: "Dashboard" },
  { to: "/inbox", label: "Inbox" },
  { to: "/review", label: "Review" },
  { to: "/settings", label: "Settings" },
];

export function AppShell() {
  const location = useLocation();
  const { data } = useQueueDashboard();
  const acknowledgeAll = useAcknowledgeAllMutation();
  const newCount = (data?.threads ?? []).filter((t) => t.is_new).length;
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
        <div className="sidebar__brand">
          <p className="sidebar__brand-sub">Inter-Op</p>
          <h2 className="sidebar__brand-title">Inter-Email</h2>
        </div>

        <nav className="nav" style={{ position: "relative" }}>
          <span
            aria-hidden="true"
            style={{
              position: "absolute",
              left: 0,
              top: indicator.top,
              width: "2px",
              height: indicator.height,
              background: "var(--accent)",
              borderRadius: "999px",
              transition: indicator.animate
                ? "top 260ms cubic-bezier(0.4, 0, 0.2, 1), height 260ms cubic-bezier(0.4, 0, 0.2, 1)"
                : "none",
              opacity: indicator.ready ? 1 : 0,
              pointerEvents: "none",
            }}
          />

          {NAV_ITEMS.map((item, index) => (
            <NavLink
              key={item.to}
              to={item.to}
              ref={(element) => { navLinkRefs.current[index] = element; }}
              style={({ isActive }) => ({
                position: "relative",
                background: "transparent",
                border: "none",
                boxShadow: "none",
                fontWeight: isActive ? 600 : 400,
                color: isActive ? "var(--text)" : "var(--muted)",
              })}
            >
              {item.label}
              {item.to === "/inbox" && newCount > 0 && (
                <button
                  className="nav-new-badge"
                  title={`${newCount} new — click to acknowledge all`}
                  onClick={(e) => { e.preventDefault(); e.stopPropagation(); acknowledgeAll.mutate(); }}
                >
                  {newCount}
                </button>
              )}
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
