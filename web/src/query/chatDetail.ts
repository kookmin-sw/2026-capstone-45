import { useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { axiosInstance } from "#root/constant.ts";

export const ChatMessageEntry = z.object({
	depth: z.int32(),
	content: z.string(),
	is_markdown: z.boolean(),
	extra_content: z.string().nullish(),
});

export const ChatDetailResponse = z.object({
	display_name: z.string(),
	has_render: z.boolean(),
	progress: z.number().nullish(),
	target_doc: z.int32(),
	source_docs: z.array(z.int32()),
	messages: z.array(ChatMessageEntry),
});

export const useQueryChatDetail = (chatId: number) =>
	useQuery({
		queryKey: ["useQueryChatDetail", chatId],
		queryFn: async () => {
			const result = await axiosInstance.get(`/chats/${chatId}`);
			const data = await ChatDetailResponse.parseAsync(result.data);
			return data;
		},
	});
