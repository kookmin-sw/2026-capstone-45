export interface Document {
	id: string;
	filename: string;
	uploadedAt: Date;
	sizeBytes: number;
	thumbnailUrl: string; // first-page raster preview
	src: string; // PDF source URL or blob URL
}

export interface Chat {
	id: string;
	title: string;
	updatedAt: Date;
	isPinned: boolean;
}

export type AppView = "LIBRARY" | "NEW_CHAT" | "CHAT" | "CHAT_AND_ARTIFACT";

export interface MenuItem {
	label: string;
	onSelect: () => void;
	variant?: "default" | "danger";
}
