import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./layout/AppShell";
import { getLang, translate } from "./i18n/core";
import { NotFound } from "./pages/NotFound";

// One bundle per page: the first page loads faster, and the charts library
// is only downloaded by the pages that use it.
const Overview = lazy(() => import("./pages/Overview").then((m) => ({ default: m.Overview })));
const Transactions = lazy(() => import("./pages/Transactions").then((m) => ({ default: m.Transactions })));
const Accounts = lazy(() => import("./pages/Accounts").then((m) => ({ default: m.Accounts })));
const CreditCards = lazy(() => import("./pages/CreditCards").then((m) => ({ default: m.CreditCards })));
const Reconciliation = lazy(() => import("./pages/Reconciliation").then((m) => ({ default: m.Reconciliation })));
const Imports = lazy(() => import("./pages/Imports").then((m) => ({ default: m.Imports })));
const ReviewQueue = lazy(() => import("./pages/ReviewQueue").then((m) => ({ default: m.ReviewQueue })));
const Places = lazy(() => import("./pages/Places").then((m) => ({ default: m.Places })));
const Points = lazy(() => import("./pages/Points").then((m) => ({ default: m.Points })));
const Budgets = lazy(() => import("./pages/Budgets").then((m) => ({ default: m.Budgets })));
const Help = lazy(() => import("./pages/Help").then((m) => ({ default: m.Help })));
const Settings = lazy(() => import("./pages/Settings").then((m) => ({ default: m.Settings })));

function PageLoading() {
  return <div className="p-8 text-sm text-ink-muted">{translate(getLang(), "app.loading")}</div>;
}

export default function App() {
  return (
    <Suspense fallback={<PageLoading />}>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<Overview />} />
          <Route path="/transactions" element={<Transactions />} />
          <Route path="/needs-review" element={<ReviewQueue />} />
          <Route path="/accounts" element={<Accounts />} />
          <Route path="/credit-cards" element={<CreditCards />} />
          <Route path="/reconciliation" element={<Reconciliation />} />
          <Route path="/reconciliation/:statementId" element={<Reconciliation />} />
          <Route path="/imports" element={<Imports />} />
          <Route path="/reports" element={<Navigate to="/" replace />} />
          <Route path="/places" element={<Places />} />
          <Route path="/points" element={<Points />} />
          <Route path="/budgets" element={<Budgets />} />
          <Route path="/help" element={<Help />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
