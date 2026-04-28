import { create } from 'zustand';

interface UIState {
  aiPanelOpen: boolean;
  toggleAIPanel: () => void;
  setAIPanelOpen: (open: boolean) => void;
}

export const useUIStore = create<UIState>()((set) => ({
  aiPanelOpen: false,
  toggleAIPanel: () => set((state) => ({ aiPanelOpen: !state.aiPanelOpen })),
  setAIPanelOpen: (aiPanelOpen) => set({ aiPanelOpen }),
}));
