'use client';

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { cn } from '@/lib/utils';

interface MarkdownRendererProps {
  /** AI 응답 등 마크다운 원문 */
  children: string;
  /**
   * 컴팩트 모드 — AIChatPanel 처럼 좁은 패널에서 사용 시 텍스트/간격 축소.
   * default: false (ai-assistant 페이지처럼 본문 폭이 넓은 곳용)
   */
  compact?: boolean;
  className?: string;
}

/**
 * AI 응답 마크다운 렌더러.
 *
 * Tailwind typography 플러그인 미설치 환경이므로 element 별 className 을 직접 매핑한다.
 * remark-gfm 으로 표(table), 체크박스, autolink 등 GFM 확장 문법을 지원한다.
 *
 * 디자인 원칙:
 * - 말풍선 안에 들어가므로 좌우 padding 은 부모(말풍선)가 책임
 * - 첫/마지막 자식의 상하 margin 은 0 으로 축소해 말풍선 안쪽이 비지 않게
 * - 줄바꿈은 마크다운 표준 그대로 (빈 줄로 단락 분리)
 */
export default function MarkdownRenderer({
  children,
  compact = false,
  className,
}: MarkdownRendererProps) {
  const text = compact ? 'text-xs' : 'text-sm';
  const subText = compact ? 'text-[11px]' : 'text-xs';

  return (
    <div
      className={cn(
        'break-words [&>*:first-child]:mt-0 [&>*:last-child]:mb-0',
        text,
        className
      )}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => (
            <p className={cn('my-2 whitespace-pre-wrap leading-relaxed')}>
              {children}
            </p>
          ),
          strong: ({ children }) => (
            <strong className="font-semibold text-gray-900">{children}</strong>
          ),
          em: ({ children }) => <em className="italic">{children}</em>,
          ul: ({ children }) => (
            <ul
              className={cn(
                'my-2 list-disc space-y-1',
                compact ? 'pl-4' : 'pl-5'
              )}
            >
              {children}
            </ul>
          ),
          ol: ({ children }) => (
            <ol
              className={cn(
                'my-2 list-decimal space-y-1',
                compact ? 'pl-4' : 'pl-5'
              )}
            >
              {children}
            </ol>
          ),
          li: ({ children }) => <li className="leading-relaxed">{children}</li>,
          h1: ({ children }) => (
            <h1
              className={cn(
                'mb-2 mt-3 font-bold text-gray-900',
                compact ? 'text-sm' : 'text-base'
              )}
            >
              {children}
            </h1>
          ),
          h2: ({ children }) => (
            <h2
              className={cn(
                'mb-2 mt-3 font-semibold text-gray-900',
                compact ? 'text-sm' : 'text-base'
              )}
            >
              {children}
            </h2>
          ),
          h3: ({ children }) => (
            <h3
              className={cn(
                'mb-1.5 mt-2 font-semibold text-gray-900',
                compact ? 'text-xs' : 'text-sm'
              )}
            >
              {children}
            </h3>
          ),
          blockquote: ({ children }) => (
            <blockquote
              className={cn(
                'my-2 border-l-2 border-gray-300 pl-3 italic text-gray-600',
                subText
              )}
            >
              {children}
            </blockquote>
          ),
          code: ({ className: codeClass, children }) => {
            const isInline = !codeClass;
            if (isInline) {
              return (
                <code className="rounded bg-gray-200 px-1 py-0.5 font-mono text-[0.85em] text-gray-800">
                  {children}
                </code>
              );
            }
            return (
              <code className="font-mono text-[0.85em]">{children}</code>
            );
          },
          pre: ({ children }) => (
            <pre
              className={cn(
                'my-2 overflow-x-auto rounded-md bg-gray-900 p-2 text-gray-100',
                subText
              )}
            >
              {children}
            </pre>
          ),
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noreferrer"
              className="text-primary-600 underline hover:text-primary-700"
            >
              {children}
            </a>
          ),
          hr: () => <hr className="my-3 border-gray-200" />,
          table: ({ children }) => (
            <div className="my-2 overflow-x-auto">
              <table
                className={cn(
                  'min-w-full border-collapse border border-gray-200',
                  subText
                )}
              >
                {children}
              </table>
            </div>
          ),
          thead: ({ children }) => (
            <thead className="bg-gray-100">{children}</thead>
          ),
          tbody: ({ children }) => <tbody>{children}</tbody>,
          tr: ({ children }) => (
            <tr className="border-b border-gray-200 last:border-b-0">
              {children}
            </tr>
          ),
          th: ({ children }) => (
            <th className="border border-gray-200 px-2 py-1 text-left font-semibold text-gray-900">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="border border-gray-200 px-2 py-1 text-gray-800">
              {children}
            </td>
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
