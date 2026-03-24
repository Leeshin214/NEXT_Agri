import type { LucideIcon } from 'lucide-react';
import { Inbox } from 'lucide-react';

interface EmptyStateProps {
  icon?: LucideIcon;
  title: string;
  description?: string;
  action?: React.ReactNode;
}

export default function EmptyState({
  icon: Icon = Inbox,
  title,
  description,
  action,
}: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl bg-white py-16 shadow-sm">
      <Icon className="h-12 w-12 text-gray-300" />
      <h3 className="mt-4 text-sm font-medium text-gray-900">{title}</h3>
      {description && (
        <p className="mt-1 text-sm text-gray-500">{description}</p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
