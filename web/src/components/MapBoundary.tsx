import { Component, type ReactNode } from 'react';

// MapLibre needs WebGL. Some phones (low-power mode, blocked WebGL, old GPUs) can't create a context;
// the walk must keep working without a map, so the failure stays inside the map's box.
export default class MapBoundary extends Component<{ children: ReactNode; className?: string }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className={this.props.className} style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', background: 'var(--bg)', color: 'var(--text-2)', fontSize: 13, padding: 24, textAlign: 'center' }}>
        The map can't be drawn on this device. Directions, check-ins and alerts still work.
      </div>
    );
  }
}
