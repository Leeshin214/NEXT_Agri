'use client';

import { useState } from 'react';
import { Send, Sparkles, X } from 'lucide-react';
import { useGenerateChatDraft } from '@/hooks/useChat';
import { cn } from '@/lib/utils';

interface MessageInputProps {
  roomId: string;
  isConnected: boolean;
  onSend: (content: string) => void;
  // 입력창 좌측에 배치되는 빠른 액션 슬롯 — PriceOfferPopover, DeliveryDatePopover 등
  leadingActions?: React.ReactNode;
}

// `/초안 ` (공백 포함) 으로 시작하면 instruction 추출. 그 외에는 null.
function parseDraftCommand(input: string): string | null {
  const trimmed = input.replace(/^\s+/, '');
  if (!trimmed.startsWith('/초안 ')) return null;
  const instruction = trimmed.slice('/초안 '.length).trim();
  if (instruction.length === 0) return null;
  return instruction;
}

// `/` 로 시작하지만 `/초안 [지시]` 패턴이 아닐 때 hint 노출용
function isSlashHintCandidate(input: string): boolean {
  return input.startsWith('/') && parseDraftCommand(input) === null;
}

export default function MessageInput({
  roomId,
  isConnected,
  onSend,
  leadingActions,
}: MessageInputProps) {
  const [message, setMessage] = useState('');
  const [draft, setDraft] = useState<string | null>(null);
  const [draftError, setDraftError] = useState<string | null>(null);

  const generateDraft = useGenerateChatDraft();

  const handleSend = () => {
    const value = message.trim();
    if (!value) return;

    // 1) `/초안 [지시]` 명령이면 초안 생성으로 분기 (메시지 전송 X)
    const instruction = parseDraftCommand(message);
    if (instruction !== null) {
      setDraft(null);
      setDraftError(null);
      generateDraft.mutate(
        { roomId, instruction },
        {
          onSuccess: (draftText) => {
            if (!draftText) {
              setDraftError('초안 생성 실패. 직접 입력해주세요.');
              return;
            }
            setDraft(draftText);
          },
          onError: () => {
            setDraftError('초안 생성 실패. 직접 입력해주세요.');
          },
        }
      );
      // 입력창은 그대로 유지 — 실패 시 사용자가 instruction 을 다시 보낼 수 있어야 함
      return;
    }

    // 2) `/초안 ` 으로 시작하지만 instruction 이 없는 경우 → 그냥 무시 (발송도, 초안도 안 함)
    //    `/` 로 시작하는 다른 메시지도 슬래시 커맨드 후보로 간주하고 발송 안 함
    if (message.startsWith('/')) return;

    // 3) 일반 메시지 발송
    onSend(value);
    setMessage('');
  };

  const handleUseDraft = () => {
    if (!draft) return;
    setMessage(draft);
    setDraft(null);
    setDraftError(null);
  };

  const handleCloseDraft = () => {
    setDraft(null);
    setDraftError(null);
  };

  const isDraftLoading = generateDraft.isPending;
  const showDraftBox = isDraftLoading || draft !== null || draftError !== null;
  const showSlashHint = isSlashHintCandidate(message);

  // 전송 버튼 활성화 조건
  // - 일반 메시지: trim 비어있지 않고 WS 연결됨
  // - `/초안 [지시]` 명령: instruction 1자 이상이면 활성 (WS 연결 무관 — draft API 는 REST)
  const trimmedMessage = message.trim();
  const isDraftCommand = parseDraftCommand(message) !== null;
  const sendDisabled = isDraftCommand
    ? isDraftLoading
    : !trimmedMessage || !isConnected || trimmedMessage.startsWith('/');

  return (
    <div className="border-t border-gray-200 p-4">
      {/* 슬래시 커맨드 hint — `/` 로 시작하고 아직 `/초안 ` 패턴이 아닐 때만 노출 */}
      {showSlashHint && !showDraftBox && (
        <div className="mb-2 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-xs text-gray-600">
          <span className="font-medium text-gray-700">/초안 </span>
          <span className="text-gray-500">
            [지시] 형식으로 입력하면 AI 답장 초안을 받을 수 있어요. 예: /초안 가격 협상해줘
          </span>
        </div>
      )}

      {/* 초안 미리보기 박스 — 로딩 / 성공 / 에러 */}
      {showDraftBox && (
        <div className="mb-2 rounded-lg border border-gray-200 bg-gray-50 p-3">
          <div className="mb-1.5 flex items-center justify-between">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-gray-700">
              <Sparkles className="h-3.5 w-3.5 text-purple-500" aria-hidden="true" />
              <span>AI 초안</span>
            </div>
            <button
              onClick={handleCloseDraft}
              disabled={isDraftLoading}
              className="flex h-6 w-6 items-center justify-center rounded-md text-gray-400 hover:bg-gray-200 disabled:opacity-40"
              aria-label="초안 닫기"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>

          {isDraftLoading ? (
            <p className="text-xs text-gray-500">초안 생성 중...</p>
          ) : draftError ? (
            <p className="text-xs text-red-500">{draftError}</p>
          ) : (
            <>
              <p className="whitespace-pre-wrap text-sm text-gray-800">{draft}</p>
              <div className="mt-2 flex items-center justify-end gap-2">
                <button
                  onClick={handleCloseDraft}
                  className="rounded-md border border-gray-200 bg-white px-3 py-1 text-xs font-medium text-gray-600 hover:bg-gray-100"
                >
                  닫기
                </button>
                <button
                  onClick={handleUseDraft}
                  className="rounded-md bg-primary-600 px-3 py-1 text-xs font-medium text-white hover:bg-primary-700"
                >
                  사용
                </button>
              </div>
            </>
          )}
        </div>
      )}

      <div className="flex gap-2">
        {leadingActions}
        <input
          value={message}
          onChange={(e) => {
            setMessage(e.target.value);
            // 사용자가 입력창을 다시 수정하면 이전 에러는 자동 dismiss
            if (draftError) setDraftError(null);
          }}
          onKeyDown={(e) => {
            if (e.nativeEvent.isComposing) return;
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              handleSend();
            }
          }}
          placeholder={
            isDraftCommand
              ? 'AI 답장 초안 요청 — Enter 를 눌러 생성'
              : '메시지를 입력하세요... (/초안 [지시] 로 AI 답장 받기)'
          }
          className={cn(
            'flex-1 rounded-lg border px-4 py-2 text-sm focus:outline-none focus:ring-1',
            isDraftCommand
              ? 'border-purple-300 bg-purple-50/50 focus:border-purple-500 focus:ring-purple-500'
              : 'border-gray-300 focus:border-primary-500 focus:ring-primary-500'
          )}
        />
        <button
          onClick={handleSend}
          disabled={sendDisabled}
          className={cn(
            'flex h-10 w-10 items-center justify-center rounded-lg text-white disabled:opacity-50',
            isDraftCommand
              ? 'bg-purple-600 hover:bg-purple-700'
              : 'bg-primary-600 hover:bg-primary-700'
          )}
          aria-label={isDraftCommand ? 'AI 초안 생성' : '메시지 전송'}
        >
          {isDraftCommand ? (
            <Sparkles className="h-4 w-4" />
          ) : (
            <Send className="h-4 w-4" />
          )}
        </button>
      </div>
    </div>
  );
}
