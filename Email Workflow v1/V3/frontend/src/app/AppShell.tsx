import { NavLink, Outlet } from "react-router-dom";

export function AppShell() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div>
          <p className="eyebrow">Inter-Op</p>
          <h2>Inter-Email</h2>
          <p className="sidebar-copy">
            Product-grade queue, review, and draft workflow.</p>
        </div>

        <nav className="nav">
          <NavLink to="/inbox">Inbox</NavLink>
          <NavLink to="/review">Review</NavLink>
          <NavLink to="/settings">Settings</NavLink>
        </nav>
      </aside>

      <main className="main-content">
        <Outlet />
      </main>
    </div>
  );
}
