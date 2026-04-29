import { create } from "zustand";

interface NewChatState {
	targetDoc: number | null;
	sourceDocs: number[];
	setTargetDoc: (id: number | null) => void;
	setSourceDocs: (ids: number[] | ((prev: number[]) => number[])) => void;
	reset: () => void;
}

export const useNewChatStore = create<NewChatState>((set) => ({
	targetDoc: null,
	sourceDocs: [],
	setTargetDoc: (targetDoc) => set({ targetDoc }),
	setSourceDocs: (sourceDocs) =>
		set((state) => ({
			sourceDocs:
				typeof sourceDocs === "function"
					? sourceDocs(state.sourceDocs)
					: sourceDocs,
		})),
	reset: () => set({ targetDoc: null, sourceDocs: [] }),
}));
