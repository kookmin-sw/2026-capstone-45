import { useMutation, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";
import { axiosInstance } from "#root/constant.ts";

export const DeleteChatResponse = z.object({
	status: z.string(),
});

export const useMutationDeleteChat = () => {
	const queryClient = useQueryClient();

	return useMutation({
		mutationFn: async (chatId: string) => {
			const result = await axiosInstance.delete(`/chats/${chatId}`);
			await DeleteChatResponse.parseAsync(result.data);
		},
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ["useQueryChatList"] });
		},
	});
};
