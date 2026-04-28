import { useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { axiosInstance } from "#root/constant.ts";

export const ChatListEntry = z.object({
	chat_id: z.int32(),
	display_name: z.string(),
	has_render: z.boolean(),
});

export type Chat = z.infer<typeof ChatListEntry>;

export const ChatListResponse = z.object({
	chats: z.array(ChatListEntry),
});

export const useQueryChatList = () =>
	useQuery({
		queryKey: ["useQueryChatList"],
		queryFn: async () => {
			const result = await axiosInstance.get("/chats");
			const data = await ChatListResponse.parseAsync(result.data);
			return data;
		},
	});
