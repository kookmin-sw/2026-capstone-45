import { create } from "zustand";
import type { AppView } from "#root/types";

interface AppState {
	view: AppView;
	sidebarFolded: boolean;
	activeChatId: string | null;
	setView: (view: AppView) => void;
	setSidebarFolded: (folded: boolean) => void;
	toggleSidebar: () => void;
	setActiveChat: (chatId: string | null) => void;
}

export const useAppStore = create<AppState>((set) => ({
	view: "NEW_CHAT",
	sidebarFolded: false,
	activeChatId: null,
	setView: (view) =>
		set((state) => ({
			view,
			// Auto-fold sidebar if transitioning to ARTIFACT view
			sidebarFolded: view === "CHAT_AND_ARTIFACT" ? true : state.sidebarFolded,
		})),
	setSidebarFolded: (sidebarFolded) => set({ sidebarFolded }),
	toggleSidebar: () =>
		set((state) => ({ sidebarFolded: !state.sidebarFolded })),
	setActiveChat: (activeChatId) => set({ activeChatId, view: "CHAT" }),
}));
