import React from "react";

import { AdminApp } from "./pages/AdminApp";
import { LoginApp } from "./pages/LoginApp";
import { VisitorApp } from "./pages/VisitorApp";

export function AppRouter() {
  const pathname = window.location.pathname;

  if (pathname === "/admin") {
    return <AdminApp />;
  }
  if (pathname === "/login") {
    return <LoginApp />;
  }
  return <VisitorApp />;
}
