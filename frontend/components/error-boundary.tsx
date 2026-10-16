"use client";
import { Component, type ReactNode } from "react";

/** Catches render errors in a page so one broken widget never blanks the whole app. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error) {
    console.error("UI error boundary caught:", error);
  }

  render() {
    if (this.state.error) {
      return (
        <div role="alert" className="m-6 rounded-lg border border-red-300 bg-red-50 p-6 text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
          <h2 className="text-lg font-semibold">This section failed to render</h2>
          <p className="mt-1 text-sm">{this.state.error.message}</p>
          <button className="mt-4 rounded-md bg-red-700 px-3 py-2 text-sm text-white" onClick={() => this.setState({ error: null })}>
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
