import { axiosInstance } from "#root/constant.ts";
import { useMutation } from "@tanstack/react-query";
import { z } from "zod";

export const CreateChatRequest = z.object({
	target_doc: z.int32(),
	source_docs: z.array(z.int32()),
	query: z.string(),
});

export const CreateChatResponse = z.object({
	chat_id: z.int32(),
});

export const useMutateCreateChat = () =>
	useMutation({
		mutationFn: async (param: z.infer<typeof CreateChatRequest>) => {
			const result = await axiosInstance.post("/chats", param);
			const data = await CreateChatResponse.parseAsync(result.data);
			return data.chat_id;
		},
	});
