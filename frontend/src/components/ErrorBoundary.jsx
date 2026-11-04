import { AlertTriangle } from "lucide-react";
import { Component } from "react";
import { Link } from "react-router-dom";
import { retryFailedPages } from "../routes/lazyPage";

/**
 * Catches a rendering error in its children so the rest of the app (sidebar,
 * header) keeps working, and shows a short message with Retry instead of a
 * blank area. No stack trace or server detail reaches the screen; in
 * development the error is logged to the console. `resetKey`: a new value
 * (e.g. the route) clears the error.
 */
export default class ErrorBoundary extends Component {
  state = { error: null, resetKey: this.props.resetKey };

  static getDerivedStateFromError(error) {
    return { error };
  }

  static getDerivedStateFromProps(props, state) {
    return props.resetKey !== state.resetKey ? { error: null, resetKey: props.resetKey } : null;
  }

  componentDidUpdate(prevProps) {
    // After moving to another route, a page whose code did not download is
    // downloaded again when next opened. Here, not during render: React may
    // render a navigation several times before showing it.
    if (prevProps.resetKey !== this.props.resetKey) retryFailedPages();
  }

  componentDidCatch(error, info) {
    if (import.meta.env.DEV) console.error("Render error caught by ErrorBoundary", error, info?.componentStack);
  }

  retry = () => {
    retryFailedPages(); // a page whose code did not download is downloaded again
    this.setState({ error: null });
    this.props.onRetry?.();
  };

  render() {
    if (!this.state.error) return this.props.children;
    const { title = "Unable to load this page" } = this.props;
    // The page's code did not download (routes/lazyPage.jsx already retried).
    const download = this.state.error.name === "ChunkLoadError";
    return (
      <div className="card error-boundary" role="alert">
        <AlertTriangle size={28} aria-hidden="true" />
        <h2>{title}</h2>
        <p className="muted">
          {download
            ? "This page could not be downloaded. Check your connection and try again."
            : "Something went wrong while displaying this page."}
        </p>
        <div className="row">
          <button type="button" onClick={this.retry}>
            Try again
          </button>
          {download && (
            // After a new deployment the old page files are gone; only a reload fetches the new ones.
            <button type="button" className="secondary" onClick={() => window.location.reload()}>
              Reload app
            </button>
          )}
          <Link to="/dashboard" className="button secondary">
            Back to Dashboard
          </Link>
        </div>
      </div>
    );
  }
}
