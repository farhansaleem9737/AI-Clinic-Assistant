import { AlertTriangle } from "lucide-react";
import { Component } from "react";
import { Link } from "react-router-dom";

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

  componentDidCatch(error, info) {
    if (import.meta.env.DEV) console.error("Render error caught by ErrorBoundary", error, info?.componentStack);
  }

  retry = () => {
    this.setState({ error: null });
    this.props.onRetry?.();
  };

  render() {
    if (!this.state.error) return this.props.children;
    const { title = "Unable to load this page" } = this.props;
    return (
      <div className="card error-boundary" role="alert">
        <AlertTriangle size={28} aria-hidden="true" />
        <h2>{title}</h2>
        <p className="muted">Something went wrong while displaying this page.</p>
        <div className="row">
          <button type="button" onClick={this.retry}>
            Try again
          </button>
          <Link to="/dashboard" className="button secondary">
            Back to Dashboard
          </Link>
        </div>
      </div>
    );
  }
}
