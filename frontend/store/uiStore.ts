import { create } from 'zustand';

/**
 * 전역 AI 채팅 컨텍스트.
 * 채팅 페이지가 현재 선택된 room_id / order_id 를 publish 하면
 * 어디서든 떠 있는 글로벌 AIChatPanel 이 이 값을 읽어 백엔드에 함께 전달한다.
 * 채팅 페이지가 언마운트되거나 방 선택을 해제하면 반드시 null 로 초기화한다.
 */
interface AIChatContext {
  roomId: string | null;
  orderId: string | null;
}

interface UIState {
  aiPanelOpen: boolean;
  toggleAIPanel: () => void;
  setAIPanelOpen: (open: boolean) => void;

  aiChatContext: AIChatContext;
  setAIChatContext: (ctx: Partial<AIChatContext>) => void;
  clearAIChatContext: () => void;
}

export const useUIStore = create<UIState>()((set) => ({
  aiPanelOpen: false,
  toggleAIPanel: () => set((state) => ({ aiPanelOpen: !state.aiPanelOpen })),
  setAIPanelOpen: (aiPanelOpen) => set({ aiPanelOpen }),

  aiChatContext: { roomId: null, orderId: null },
  setAIChatContext: (ctx) =>
    set((state) => ({
      aiChatContext: { ...state.aiChatContext, ...ctx },
    })),
  clearAIChatContext: () =>
    set({ aiChatContext: { roomId: null, orderId: null } }),
}));
