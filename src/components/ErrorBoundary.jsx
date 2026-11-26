import { Component } from 'react';

export default class ErrorBoundary extends Component {
  state = { failed: false };

  static getDerivedStateFromError() { return { failed: true }; }

  componentDidCatch() {
    // Error messages/component props can contain candidate or authentication data.
    console.error('[UI] Rendering failed; recovery screen displayed.');
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <main role="alert" className="min-h-screen bg-surface text-heading flex items-center justify-center p-6">
        <div className="glass-card p-6 max-w-md space-y-4">
          <h1 className="text-xl font-semibold">This screen couldn’t be displayed</h1>
          <p className="text-secondary">Reload to try again. Saved progress will remain on this device; unsaved changes may need to be entered again.</p>
          <button type="button" onClick={() => window.location.reload()}
            className="btn-primary">
            Reload screen
          </button>
        </div>
      </main>
    );
  }
}
