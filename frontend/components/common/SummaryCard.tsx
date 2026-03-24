'use client';

import { cn } from '@/lib/utils';
import type { LucideIcon } from 'lucide-react';

interface SummaryCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon: LucideIcon;
  iconColor?: string;
  trend?: { value: number; label: string };
  onClick?: () => void;
}

export default function SummaryCard({
  title,
  value,
  subtitle,
  icon: Icon,
  iconColor = 'text-primary-600 bg-primary-100',
  trend,
  onClick,
}: SummaryCardProps) {
  return (
    <div
      className={cn(
        'rounded-xl bg-white p-6 shadow-sm',
        onClick && 'cursor-pointer hover:shadow-md transition-shadow'
      )}
      onClick={onClick}
    >
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm text-gray-500">{title}</p>
          <p className="mt-1 text-2xl font-semibold text-gray-900">{value}</p>
          {subtitle && (
            <p className="mt-1 text-xs text-gray-400">{subtitle}</p>
          )}
          {trend && (
            <p
              className={cn(
                'mt-1 text-xs font-medium',
                trend.value >= 0 ? 'text-green-600' : 'text-red-600'
              )}
            >
              {trend.value >= 0 ? '+' : ''}
              {trend.value}% {trend.label}
            </p>
          )}
        </div>
        <div
          className={cn(
            'flex h-10 w-10 items-center justify-center rounded-lg',
            iconColor
          )}
        >
          <Icon className="h-5 w-5" />
        </div>
      </div>
    </div>
  );
}
