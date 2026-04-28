import { useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { axiosInstance } from "#root/constant.ts";

export const ChatListEntry = z.object({
	display_name: z.string(),
	has_render: z.string(),
});

export const ChatListResponse = z.object({
	chats: z.array(ChatListEntry),
});

export const useQueryChatList = () =>
	useQuery({
		queryKey: ["useQueryChatList"],
		queryFn: async () => {
			const result = await axiosInstance.get("/chats");
			const data = await ChatListResponse.parseAsync(result);
			return data;
		},
	});
