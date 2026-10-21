import type { Metadata } from 'next';
import { MonitoringView } from './monitoring-view';

export const metadata: Metadata = { title: 'Monitoring' };

export default function MonitoringPage() {
  return <MonitoringView />;
}
