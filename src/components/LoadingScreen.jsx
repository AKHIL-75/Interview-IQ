import { Loader2, Brain } from 'lucide-react';

export default function LoadingScreen({ message = 'Loading...', submessage = '' }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-surface ">
      <div className="text-center">
        <div className="relative mb-6">
          <div className="w-16 h-16 rounded-full bg-selected flex items-center justify-center mx-auto">
            <Brain className="w-8 h-8 text-primary animate-pulse" />
          </div>
          <Loader2 className="w-20 h-20 text-primary animate-spin absolute -top-2 -left-2 mx-auto" style={{ left: 'calc(50% - 40px)' }} />
        </div>
        <p className="text-heading font-medium text-lg">{message}</p>
        {submessage && <p className="text-secondary text-sm mt-2">{submessage}</p>}
      </div>
    </div>
  );
}

export function InlineLoader({ message = 'Processing...' }) {
  return (
    <div className="flex items-center justify-center gap-3 py-8">
      <Loader2 className="w-5 h-5 text-primary animate-spin" />
      <span className="text-secondary text-sm">{message}</span>
    </div>
  );
}
