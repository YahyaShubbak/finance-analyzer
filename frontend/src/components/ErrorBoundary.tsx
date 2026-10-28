import { Component, type ErrorInfo, type ReactNode } from "react";
import { getLang, translate } from "../i18n/core";

interface State {
  error: Error | null;
}

/** Catches render errors so one broken widget shows a message instead of
 * turning the whole app into a blank page. Give it `key={route}` so that
 * navigating to another page mounts a fresh boundary and recovers. */
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Unhandled UI error", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="p-8">
        <div role="alert" className="max-w-xl rounded-lg border border-danger/20 bg-danger-soft p-5 text-sm">
          <div className="font-semibold text-danger">{translate(getLang(), "error.title")}</div>
          <p className="text-ink-muted mt-1">{translate(getLang(), "error.body")}</p>
          <pre className="mt-3 text-xs text-ink whitespace-pre-wrap break-words">{this.state.error.message}</pre>
          <button
            type="button"
            className="mt-4 inline-flex px-3.5 py-2 rounded-md text-sm font-medium bg-accent text-white hover:bg-accent-strong"
            onClick={() => window.location.reload()}
          >
            {translate(getLang(), "error.reload")}
          </button>
        </div>
      </div>
    );
  }
}
