import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  /** What failed, in the reader's terms - e.g. "The price chart". */
  label: string;
}

interface State {
  error: Error | null;
}

/**
 * Keeps one broken panel from taking down the whole dashboard.
 *
 * Added after a real incident: hovering the trend line threw inside the
 * scatter chart's tooltip, and because nothing caught it, React unmounted
 * the entire app - the page just went blank. A crash should cost you one
 * panel, not the page.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`[${this.props.label}] render failed`, error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="rounded-lg border border-status-serious/40 bg-surface-1 p-4 text-sm">
          <p className="font-medium text-primary">{this.props.label} couldn't be displayed.</p>
          <p className="mt-1 text-xs text-muted">
            The rest of the dashboard still works. Reload the page to try again — if it keeps happening, the details are
            in the browser console.
          </p>
          <button
            type="button"
            onClick={() => this.setState({ error: null })}
            className="mt-2 rounded-md border border-border px-2 py-1 text-xs text-secondary hover:text-primary"
          >
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
