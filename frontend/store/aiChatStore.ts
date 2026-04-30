import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

/**
 * AI 대화 캐시 스토어
 *
 * - 사용자가 보낸 prompt(=대화 turn) 기준으로 100개를 cap
 * - localStorage 에 persist → 새로고침/페이지 이동에도 즉시 표시
 * - 로그아웃 시 useAuth.signOut() 에서 clearMessages() 호출로 초기화
 *
 * authStore 와 달리 탭별 격리는 적용하지 않음 (AI 대화는 사용자별 글로벌).
 * 다만 같은 노트북에서 다른 계정으로 로그인하는 경우를 대비해 로그아웃 시 반드시 비운다.
 */

const TURNS_CAP = 100;

export interface AIChatTurn {
  id: string; // DB id 또는 임시 id (uuid)
  prompt: string;
  response: string;
  prompt_type: string | null;
  created_at: string; // ISO string
  pending?: boolean; // true면 응답 대기 중 (response="")
}

interface AIChatState {
  turns: AIChatTurn[]; // 오래된순 정렬 유지
  hydrated: boolean; // DB history 와 머지 완료 여부 (세션당 1회 권장이지만 재호출도 허용)
}

interface AIChatActions {
  /** 새 turn 을 pending 상태로 추가하고 임시 id 를 반환 */
  addPendingTurn: (prompt: string, prompt_type?: string | null) => string;
  /** 응답 도착 시 tempId 매칭해서 finalize */
  resolveTurn: (
    tempId: string,
    finalTurn: { id?: string; response: string; created_at?: string }
  ) => void;
  /** 응답 실패 시 tempId 매칭해서 에러 메시지로 finalize */
  failTurn: (tempId: string, errorResponse: string) => void;
  /** DB 에서 받은 turns 로 통째로 교체. 호출 시점마다 항상 갱신 (이미 hydrated 라도 덮어씀) */
  hydrateFromHistory: (turns: AIChatTurn[]) => void;
  /** 로그아웃 시 호출 — turns 비우고 hydrated=false */
  clearMessages: () => void;
}

type AIChatStore = AIChatState & AIChatActions;

function generateTempId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `tmp-${crypto.randomUUID()}`;
  }
  return `tmp-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

/** 가장 오래된 turn 부터 잘라서 cap 이하로 유지 */
function trimToCap(turns: AIChatTurn[]): AIChatTurn[] {
  if (turns.length <= TURNS_CAP) return turns;
  return turns.slice(turns.length - TURNS_CAP);
}

export const useAIChatStore = create<AIChatStore>()(
  persist(
    (set) => ({
      turns: [],
      hydrated: false,

      addPendingTurn: (prompt, prompt_type) => {
        const tempId = generateTempId();
        set((state) => {
          const next: AIChatTurn = {
            id: tempId,
            prompt,
            response: '',
            prompt_type: prompt_type ?? null,
            created_at: new Date().toISOString(),
            pending: true,
          };
          return { turns: trimToCap([...state.turns, next]) };
        });
        return tempId;
      },

      resolveTurn: (tempId, finalTurn) => {
        set((state) => ({
          turns: state.turns.map((t) =>
            t.id === tempId
              ? {
                  ...t,
                  id: finalTurn.id ?? t.id,
                  response: finalTurn.response,
                  created_at: finalTurn.created_at ?? t.created_at,
                  pending: false,
                }
              : t
          ),
        }));
      },

      failTurn: (tempId, errorResponse) => {
        set((state) => ({
          turns: state.turns.map((t) =>
            t.id === tempId
              ? {
                  ...t,
                  response: errorResponse,
                  pending: false,
                }
              : t
          ),
        }));
      },

      hydrateFromHistory: (turns) => {
        // 항상 cap 이하로 유지 (호출자가 이미 잘라서 줘도 안전 가드)
        set({ turns: trimToCap(turns), hydrated: true });
      },

      clearMessages: () => {
        set({ turns: [], hydrated: false });
      },
    }),
    {
      name: 'ai-chat-storage',
      storage: createJSONStorage(() =>
        typeof window !== 'undefined'
          ? window.localStorage
          : (undefined as unknown as Storage)
      ),
      partialize: (state) => ({
        turns: state.turns,
        hydrated: state.hydrated,
      }),
    }
  )
);
